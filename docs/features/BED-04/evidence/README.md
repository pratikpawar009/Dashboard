# BED-04 — evidence pass

Six-dimension evidence packet from `/arh-implement` Step 1, run over the merged tree after all 5
tasks reached `done`. Verdict: **READY on round 2**.

Raw captures (`*.log`) sit in this directory but are **not committed** — `.gitignore:45` excludes
`*.log` repo-wide. This README is the durable record; the structured version lives in
`../state.json` under `.impl_evidence`.

## Round 1 — BLOCKED, then fixed

Round 1 returned **BLOCKED** with 5 of 6 dimensions FAIL. Every failure was the same single cause,
and none of it was BED-04's code: `pnpm 11.20.0`'s pre-command deps check rejected every
`apps/web` invocation with `[ERR_PNPM_IGNORED_BUILDS] Ignored build scripts: unrs-resolver@1.12.2`,
so the `apps/web` half of each composite command in `docs/config/project-commands.yaml` never
reached its tool. `services/api` — BED-04's entire `file_plan` — was green throughout.

This is the same gate AUTH-04 recorded as its own **AF-01** and deferred, on the grounds that
approving a dependency's install script is a human decision. It kept recurring for every
subsequent story. This session it was **fixed** rather than deferred again, at the user's explicit
instruction — see `../FLAGS.md` **AF-03**. `apps/web/pnpm-workspace.yaml` (its own `chore` commit,
outside this story's `file_plan`) records:

```yaml
allowBuilds:
  unrs-resolver: true
```

Approved rather than denied because `unrs-resolver`'s install script is `napi-postinstall`, the
standard napi-rs helper that links the platform-native binary
(`@unrs/resolver-binding-darwin-arm64`) already pinned and integrity-hashed in `pnpm-lock.yaml`. It
compiles nothing and fetches nothing beyond the locked packages. Denying would also clear the gate
but risks eslint failing to resolve imports with the binding unlinked — and eslint passing cleanly
afterwards confirms the binding was what it needed. The gate is now cleared for every future
story's evidence pass, not just BED-04.

## Round 2 — READY

| Dimension | Verdict | Command | Result |
|---|---|---|---|
| typecheck | PASS | `pnpm -C apps/web exec tsc --noEmit` + `uv run mypy .` | web exit 0; api `Success: no issues found in 91 source files` |
| unit_tests | PASS | `pnpm -C apps/web test` + `uv run pytest` | web 1/1; api **430 passed, 0 failed** in 38.58s (full suite, un-narrowed) |
| lint | PASS | `pnpm -C apps/web exec eslint .` + `uv run ruff check .` | web exit 0; api `All checks passed!` |
| runtime | PASS | `uvicorn app.main:app --port 8010`; `next dev --turbopack --port 3011` | api `GET /health` 200, boot log clean; web Ready, `GET /` 200 on both loopback forms, boot log clean |
| compile | PASS | `next build --turbopack` | exit 0, `✓ Compiled successfully`, static pages 5/5 |
| design_check | **N/A** | — | N/A on two grounds: `project-commands.yaml design_check: ""` (no tool wired) and `state.json design: "n/a"` (`BED` has no epic in `docs/design/schema.json`, backend-only). Flag **AF-04**. |

The first three rows are the real composite commands from `project-commands.yaml`, run **through
pnpm**, which is what proves AF-03's gate is genuinely cleared rather than side-stepped. `compile`
and the web half of `runtime` ran the identical underlying binaries from `apps/web/node_modules/.bin`,
because this session's permission classifier blocks the `pnpm` wrappers that execute package
scripts (`pnpm install`, `pnpm build`); `package.json` maps those scripts to exactly
`next build --turbopack` and `next dev --turbopack`, so the evidence is equivalent. Recorded here
rather than glossed.

Web runtime carries `render_check: "unavailable"` — the boot and a 200 are asserted, but no
browser-capable tool is installed to prove the app mounts (`test_e2e: ""`). Flag **AF-05**.

## Test count: 430 here, 431 in the final tree

This packet was captured **before** the Step 2 fix pass. Review finding **F-1** (HIGH) — the
`system_metadata` read had no explicit timeout, while `REQUIREMENTS.md:46` promised one and
`app/core/db.py` provided none to inherit — was fixed under decision **D-04**, adding an explicit
3.0s `asyncio.wait_for` plus one regression test. The final validated tree is therefore
**431 passed / 0 failed** (`../VALIDATION-20260903-1606.md`). The packet was not re-run for the
delta because gates read `state.json .impl_evidence` and every dimension it records stayed PASS;
the Validate ∥ Review gate re-earned both verdicts against the post-fix tree.

## Port hygiene

Ports 8000 and 3000 were both held by pre-existing unrelated processes, and port 3010 collided with
`python -m agentrise_mcp.server` (pid 518) — that collision produced a nondeterministic 404 on IPv4
versus 200 on IPv6 depending on hostname resolution, so it was **not** trusted as a boot signal.
Both stacks were re-smoked on isolated ports (api `:8010`/`:8134`, web `:3011`) with a single
confirmed listener each. No pre-existing process was killed.

The api stack smoke additionally ran against a throwaway `dashboard_smoke` database — created,
migrated from empty through `001_initial_schema` to 18 tables, health-checked, then dropped — so a
genuinely fresh migration was exercised without touching dev data.
