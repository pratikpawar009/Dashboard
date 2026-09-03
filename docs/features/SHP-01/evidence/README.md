# SHP-01 — evidence pass

Six-dimension evidence packet from `/arh-implement` Step 1, run over the merged tree after all 12
tasks reached `done`. Verdict: **READY on round 1** — no dimension failed, so no internal fix loop
ran and no `EVIDENCE-ESCALATION.md` was written.

Raw captures (`*.log`) sit in this directory but are **not committed** — `.gitignore:45` excludes
`*.log` repo-wide. This README is the durable record; the structured version lives in
`../state.json` under `.impl_evidence`.

## Round 1 — READY

| Dimension | Verdict | Command | Result |
|---|---|---|---|
| typecheck | PASS | `pnpm -C apps/web exec tsc --noEmit` + `uv run mypy .` | web exit 0; api `Success: no issues found in 91 source files` |
| unit_tests | PASS | `pnpm -C apps/web test` + `uv run pytest tests/` | web 5 files / 14 tests passed; api **431 passed** in 45.31s |
| lint | PASS | `pnpm -C apps/web exec eslint .` + `uv run ruff check .` | web exit 0; api `All checks passed!` |
| runtime | PASS | `uvicorn app.main:app --port 8010`; `pnpm dev --port 3021` | api `GET /health` → 200 `{"status":"ok"}`, boot log clean; web boot clean, `GET /` → 200 with full SSR markup |
| compile | PASS | `pnpm -C apps/web build` | exit 0, `Compiled successfully`, static pages 5/5 |
| design_check | **N/A** | — | `project-commands.yaml design_check: ""` — no a11y/console-error/perf tool wired, with the reasoning recorded inline in that file. Flag **AF-07**, triaged `defer` → `AF-07-carry`. |

SHP-01 is frontend-only: it adds no route, env var, service, port, or runtime dependency, and touches
nothing under `services/api/`. `apps/web/package.json` and `apps/web/vitest.config.ts` are deliberately
unchanged (a PLAN.md § Runner-setup decision — the performance test runs in the existing runner via
`performance.now()`, and `@testing-library/jest-dom` was intentionally not added). Step 4's config-drift
companion edit therefore has no trigger. The `services/api` halves of each composite command above ran
anyway, because that is what `docs/config/project-commands.yaml` specifies — they are regression
evidence for the untouched backend, not evidence about this story's diff.

## What the web runtime check does and does not prove

The check renders `apps/web/src/app/page.tsx` — the untouched default App Router scaffold — because
`PersonaDashboardShell` has **no in-repo route consumer**. That is the plan-documented story boundary
(PLAN.md § 6 Cross-Feature Dependency Notes; PRD § Scope puts composing-page work in
ARC-01/DEV-01/PMD-01/EMD-01), carried forward as `R-01-session-seam-unowned` and
`R-02-persona-resolver-callsite-unowned`. So the runtime row proves the app still boots and serves with
this story's code in the tree; it does not exercise the shell in a browser. No browser-capable runner is
installed (`test_e2e: ""`), so the shell's render is proven by jsdom instead — 14 vitest assertions
across TC-01/02/03/04, including the loading-suppression and error-badge paths.

## Port hygiene

Ports 8000 and 3000 were held by pre-existing unrelated processes, and the first alternate chosen for
web, 3010, turned out to be squatted by `python -m agentrise_mcp.server`, which answers with a
misleading `server: uvicorn` 404 — not a Next.js defect, and deliberately not trusted as a boot signal.
Both stacks were re-smoked on confirmed-free ports (api `:8010`, web `:3021`) with a throwaway Postgres
container on `:5434`, migrated `alembic upgrade head` from empty, then torn down. No pre-existing
process was killed.

## Carried forward from this pass, not fixed

`apps/web/vitest.config.ts` emits a Vite `configLoader: 'native'` future-default warning (ESM syntax in
a file loaded as CommonJS). Pre-existing, unrelated to this story, and outside its `file_plan` — left
alone per `.claude/rules/surgical-changes.md` rather than opportunistically fixed.
