# BED-05 — evidence pass

Six-dimension evidence packet from `/arh-implement` Step 1, run over the merged tree after all 13
tasks reached `done`. Verdict: **READY on round 1.**

Raw captures (`*.log`) sit in this directory but are **not committed** — `.gitignore:45` excludes
`*.log` repo-wide. This README is the durable record; the structured version lives in
`../state.json` under `.impl_evidence`.

One deviation from the usual shape, recorded for auditability: the packet was run **inline by the
`/arh-implement` orchestrator**, not by an `implementation-agent` in `--evidence` mode. Subagent
dispatch was unavailable for part of this session (API session rate limit), and
`steps/01-implement.md` § Procedure permits the fallback explicitly — "If `Task` is unavailable, run
the batch sequentially instead; never skip tasks." The same four tasks affected by that limit (T-05,
T-06, T-07, T-08) were likewise completed inline; each records this in its `tasks.json` completion
`reason`.

## Round 1 — READY, all six dimensions green

| Dimension | Status | Capture | Result |
|---|---|---|---|
| `typecheck` | **PASS** | `typecheck.log` | `pnpm tsc --noEmit` clean; `mypy` 0 issues across 120 source files |
| `unit_tests` | **PASS** | `unit-tests.log` | web `vitest` 20 files / 99 tests; api `pytest` 507 passed |
| `lint` | **PASS** | `lint.log` | `eslint` clean; `ruff check` "All checks passed!" |
| `runtime` | **PASS** | `runtime-fastapi-2.log`, `runtime-nextjs.log` | both applicable stacks — see below |
| `compile` | **PASS** | `compile.log` | `pnpm -C apps/web build` exit 0 |
| `design_check` | **N/A** | — | flag `AF-10`, triaged `reject` (N/A confirmed) |

### Runtime, per stack

Both stacks were smoked on their **canonical** ports rather than alternates, and both were stopped
afterwards so the ports were released.

- **`fastapi-2`** — `uvicorn` on port **8000**. `/health` returned `200` after 3s, `/docs` `200`.
  Boot-log scan for `Error|Exception|Panic|FATAL|fatal`: **0 matches**.
- **`nextjs`** — `pnpm dev` on port **3000**. Ready in 1112ms, compiled and served `GET /` → `307`
  (the expected auth redirect). Boot-log scan: **0 matches**. This stack exposes no `/health` route,
  so the root page was smoked instead — a documented deviation from the dimension's stated
  `/health`-returns-200 criterion.

One pre-existing failure was observed and deliberately **not** attributed to this feature: `/` redirects
to `/overview`, which returns **404**. No `/overview` route exists in `apps/web/src/app` (only `api`,
`callback`, `login`, `programs`), `OVW-01`..`OVW-04` are all at `impl: None`, and BED-05 touched zero
`apps/web/**` files. The validation-agent independently reconfirmed this during the Step 2 gate.

## `design_check` — why N/A rather than FAIL

Doubly inapplicable, which is why `AF-10` was triaged as `reject` (N/A confirmed) rather than
deferred:

1. `docs/config/project-commands.yaml` leaves `design_check` empty **on purpose** — its own comment
   records that no accessibility / console-error-scan / perf tool has been chosen or wired yet.
2. BED-05 is backend-only. Its `design` field is `n/a`, legitimately: `docs/design/schema.json` maps
   mockups to `OVW`/`PGD`/`EMD`/`ARC`/`DEV`/`PMD` only, and there is no `BED` epic there. There is no
   UI surface for a design check to examine even if a tool existed.

## Note on the test count

`unit-tests.log` shows **507** api tests. T-07's own preflight, captured earlier in the session,
recorded **505**. Both are correct and neither contradicts the other: T-08 replaced BED-03-TC-15's
single empty-table assertion with three table-size-indexed tests (net **+2**), and T-09/T-10 added
their own files after T-07's preflight had already run. Every count in the session showed **0
failures**. The Step 2 validation-agent flagged and resolved this same drift independently.
