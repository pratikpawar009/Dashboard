# AUTH-03 — evidence pass

Six-dimension evidence packet from `/arh-implement` Step 1, run once over the merged tree after
all seven tasks reached `done`. Verdict: **READY on round 1** — no fix loop entered.

The raw captures (`typecheck.log`, `unit-tests.log`, `lint.log`, `runtime-api.log`,
`runtime-web.log`, `compile.log`) sit in this directory but are **not committed** — `.gitignore`
excludes `*.log` repo-wide. This README is the durable record; the structured version lives in
`../state.json` under `.impl_evidence`.

| Dimension | Verdict | Command | Result |
|---|---|---|---|
| typecheck | PASS | `pnpm -C apps/web exec tsc --noEmit && cd services/api && uv run mypy .` | `Success: no issues found in 78 source files`, exit 0 |
| unit_tests | PASS | `pnpm -C apps/web test && cd services/api && uv run pytest` | web 1/1; api **377 passed, 0 failed, 0 skipped** in 13.32s |
| lint | PASS | `pnpm -C apps/web exec eslint . && cd services/api && uv run ruff check .` | `All checks passed!`, exit 0 |
| runtime | PASS | uvicorn (api) + `pnpm dev` (web) | api boot clean, `GET /health -> 200`; web boot clean, `GET / -> 200` |
| compile | PASS | `pnpm -C apps/web build` + `python -m compileall` | `✓ Compiled successfully`, static pages 5/5, exit 0 |
| design_check | **N/A** | — | N/A on two grounds: `project-commands.yaml design_check: ""` (no tool wired) and `state.json design: "n/a"` (backend-only, no UI surface). Flag AF-02. |

## Two things the packet proved that unit tests could not

**D-06 wiring, live.** A throwaway `create_app()` confirmed
`app.core.rbac._persona_resolver is app.state.persona_resolver` — the same `PersonaResolver`
instance. This is the one failure mode no unit test can catch: every test calls
`rbac.configure(stub)` directly, so a missing `configure()` call in `create_app()` would leave
the suite fully green while every persona-resolving check raised `RuntimeError` on the first
real request.

**Full-suite regression check.** Per-task workers only ran their own files. `main.py`'s new
`rbac.configure()` line sits in a path every `app.main` importer touches, so only the full
377-test run could prove nothing upstream broke. It included `tests/test_migrations.py` against
a genuinely live Postgres.

## Not fixed here, deliberately

`uv run ruff format --check .` (supplementary — **not** part of the canonical `lint:` command,
which passes) reports one formatting drift at `services/api/README.md:26`, inside the
pre-existing `## Session factory` section. Verified byte-identical to
`git show HEAD:services/api/README.md` since commit `1d3f740` (AUTH-02) and untouched by this
feature's insertion-only diff. `.claude/rules/surgical-changes.md` forbids fixing adjacent
unrelated content, so it is recorded as flag AF-04 instead.
