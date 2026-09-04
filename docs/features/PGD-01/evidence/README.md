# PGD-01 — evidence pass

Six-dimension evidence packet from `/arh-implement` Step 1, run over the merged tree after all 15
tasks reached `done` (plus the AF-05 corrective pass). Verdict: **READY on round 1** — no dimension
failed, so no internal fix loop ran and no `EVIDENCE-ESCALATION.md` was written.

Raw captures (`*.log`) sit in this directory but are **not committed** — `.gitignore:45` excludes
`*.log` repo-wide. This README is the durable record; the structured version lives in
`../state.json` under `.impl_evidence`.

## Round 1 — READY

| Dimension | Verdict | Command | Result |
|---|---|---|---|
| typecheck | PASS | `pnpm -C apps/web exec tsc --noEmit` + `uv run mypy .` | web exit 0; api `Success: no issues found in 95 source files` |
| unit_tests | PASS | `pnpm -C apps/web test` + `uv run pytest tests/` | web 13 files / 54 tests passed; api **434 passed** |
| lint | PASS | `pnpm -C apps/web exec eslint .` + `uv run ruff check .` | web exit 0; api `All checks passed!` |
| runtime | PASS | `uvicorn app.main:app --port 8010`; `pnpm dev --port 3021` | api `/health` → 200, dev-bypass token minted, `GET /api/overview/program-detail/{id}` → 200 seeded / 404 unknown / 401 no-bearer, `program_drilldown` + `program_switch` each logged exactly once; web `/` and `/programs/prog-smoke-01` → 200, boot logs clean both stacks. Flag **AF-07** (render_check unavailable), triaged `accept`. |
| compile | PASS | `pnpm -C apps/web build` | `next build --turbopack` exit 0; route table lists `ƒ /programs/[program_id]` |
| design_check | **N/A** | — | `project-commands.yaml design_check: ""` — no a11y/console-error/perf tool wired, reasoning recorded inline in that file. Flag **AF-06**, triaged `accept`. |

Unlike SHP-01, this story is full-stack: it adds a backend route, a frontend route, and the repo's
first `apps/web` env var. The config-drift companion edits therefore did fire — `README.md`
(API + env tables, T-14), `apps/web/.env.example` (new, T-14) and `docs/config/stack-smoke.md`
(T-15) are all part of the diff.

## What the web runtime check does and does not prove

The check renders the real story route, `/programs/prog-smoke-01` — unlike SHP-01, this story ships
its own page, so there is no unowned-consumer gap. No browser-capable runner is installed
(`test_e2e: ""`), so the packet could make no formal `render_check` assertion; a curl of the SSR
HTML showed real rendered content ("Back to program board", the error-panel copy) rather than an
empty mount node. Component behaviour is proven by jsdom instead — 54 vitest assertions, of which
TC-03's six cover switch-reload, `router.replace` (no hard nav), the back-link target, the 404
error state, and the switcher's aria/keyboard contract.

## The SSR 401 is expected, not a defect

During the runtime check the server-rendered fetch to the backend returned **401**.
`programDetailApi.ts` deliberately sends no `Authorization` header (**D-08**) because no frontend
session/token-acquisition mechanism exists anywhere in `apps/web` yet. The page handled it by
rendering its documented error state (D-03) rather than crashing — so this is confirmation of
correct degradation, not a new defect. Tracked as the `frontend-auth-token-gap` carry-forward,
owner: a future frontend auth/session story.

## Port hygiene

Ports 8000 and 3000 were held by pre-existing unrelated processes, so both stacks were smoked on
confirmed-free ports (api `:8010`, web `:3021`) against a throwaway `postgres:16` container on
`:5435`, migrated `alembic upgrade head` from empty, then torn down. No pre-existing process was
killed. A port answering was never treated on its own as proof a server had started — the boot log
and process were checked too.
