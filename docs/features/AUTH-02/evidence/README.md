# Evidence packet — AUTH-02

Six-dimension evidence pass. Rounds: 2 — re-run after the Step 2 fix loop added `tier3_latency_ms` (D-11).
Run 2026-08-28 in worktree `.claude/worktrees/auth-02` on branch `feature/AUTH-02`.

| Dimension | Result | Command | Evidence |
|---|---|---|---|
| Typecheck | PASS | `uv run mypy .` / `tsc --noEmit` | mypy: `Success: no issues found in 75 source files`; tsc: exit 0, no output |
| Unit tests | PASS | `uv run pytest tests/` / `pnpm test` | backend `334 passed`; web `1 passed`. See AF-03 for perf-suite flakiness. |
| Lint | PASS | `uv run ruff check .` / `eslint .` | ruff: `All checks passed!`; eslint: exit 0, 0 findings |
| Runtime | PASS | `uvicorn app.main:app` + `GET /health` | `200 {"status":"ok"}`, boot log free of errors/tracebacks |
| Compile | PASS | `pnpm -C apps/web build` | Next.js production build succeeded, static prerender emitted |
| Design check | N/A | (unset) | `docs/config/project-commands.yaml` `design_check: ""` — no a11y/perf tool wired. AF-04. |

## Notes

`TEST_DATABASE_URL` had to be set to a reachable disposable Postgres for the Tier-3 cases
(`AUTH-02-TC-03`, `TC-13`, `TC-14`) — see AF-02. The runs above used
`postgresql+psycopg://postgres:postgres@localhost:5443/dashboard_test`.

The backend `pytest tests/` figure includes AUTH-02's own 18 new tests: 16 in
`tests/unit/test_persona_resolver.py` (AUTH-02-TC-01..11, 14, 15, plus 3 TC-16 cases added in the fix loop) and 2 in
`tests/perf/test_persona_resolver_perf.py` (TC-12, TC-13). All 18 pass in isolation; see AF-03 for the warm-hit p99 measurements.
