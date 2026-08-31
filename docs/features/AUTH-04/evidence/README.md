# AUTH-04 — evidence pass

Six-dimension evidence packet from `/arh-implement` Step 1, run once over the merged tree after
all 13 tasks reached `done`. Verdict: **READY on round 1** — no fix loop entered.

Raw captures (`*.log`) sit in this directory but are **not committed** — `.gitignore` excludes
`*.log` repo-wide. This README is the durable record; the structured version lives in
`../state.json` under `.impl_evidence`.

Run in the main orchestrator session rather than by an `implementation-agent --evidence` worker:
the worker was terminated mid-run by an API rate limit (session limit, model `claude-sonnet-5`).
Every command below was executed for real and its output captured; nothing is inferred. Step 1's
own note applies — the gates read `state.json .impl_evidence` and are agnostic to where the
evidence ran.

| Dimension | Verdict | Command | Result |
|---|---|---|---|
| typecheck | PASS | `tsc --noEmit` (web) + `uv run mypy .` (api) | web exit 0; api `Success: no issues found in 82 source files` |
| unit_tests | PASS | `vitest run` (web) + `uv run pytest` (api) | web 1/1; api **395 passed, 0 failed** in 19.23s (18 are AUTH-04's: 17 unit + 1 perf) |
| lint | PASS | `eslint .` (web) + `uv run ruff check .` (api) | web exit 0; api `All checks passed!` |
| runtime | PASS | `uvicorn app.main:app --port 8123` against Postgres on :5442 | boot log clean (0 tracebacks); `GET /health` 200; `GET /api/programs` 401 unauthenticated, 403 fail-closed, 200 with the exact ADR-0005 key set |
| compile | PASS | `next build` (web); api is interpreted, no compile step | `✓ Compiled successfully in 6.3s`, static pages 5/5, exit 0 |
| design_check | **N/A** | — | N/A on two grounds: `project-commands.yaml design_check: ""` (no tool wired) and `state.json design: "n/a"` (backend-only, no UI surface). Flag **AF-02**. |

## What the runtime dimension proved that the unit tests could not

The 17 unit tests all run against FastAPI's test client with `app.dependency_overrides` swapping
in a disposable session and a stubbed persona resolver. The runtime check booted the **real
server process** against a **real Postgres** with **no overrides**, and exercised three paths:

- **401 unauthenticated** — `{"error":{"code":"http_401","message":"invalid_token"}}`.
- **403 fail-closed (FR-3 / condition C-3), unplanned but exactly correct.** The first authenticated
  request returned 403, because that database's `persona_config` table is empty and
  `PERSONA_ROLE_MAP` was unset — all three resolver tiers came up empty. The server logged
  `programs_persona_resolution_failed` at WARNING with `reason: "not_found"` (the
  `PersonaNotFoundError` branch) and returned `403 "Access denied"`, **never a 500**. This is the
  fail-closed contract demonstrated against a live stack, not a stub.
- **200 with the contract shape.** With `PERSONA_ROLE_MAP='{"cio":"cio"}'` supplying Tier-1, the
  response was
  `{"programs":[{"program_id":"demo-prog","label":"","href":"/api/overview/program-detail/demo-prog","dotStyle":"background-color: #d97757;"}]}`
  — key set exactly `{program_id, label, href, dotStyle}`, `href` correct, `dotStyle` a
  pre-formatted CSS declaration, and none of `type` / `description` / `name` / `icon` / `current` /
  `rowStyle` present. (`label` is empty because that borrowed row's `name` column is empty — a
  data artifact of the ad-hoc database, not a mapping defect.)
- **The C-1 PII allowlist, live.** The emitted record was
  `{timestamp, level, logger, message, user_id, persona, returned_count}` — no `email`, no
  `groups`, no request path, in real `JSONFormatter` output rather than a test's formatted record.

Port ownership was confirmed with `lsof -nP -iTCP:8123 -sTCP:LISTEN` before trusting any response;
port 8000 is occupied by two unrelated stale servers, so a response from it would have proved
nothing.

## Not fixed here, deliberately

The canonical composite commands in `docs/config/project-commands.yaml` all begin with a
`pnpm -C apps/web …` segment, and **every one of them fails before reaching its tool** —
`pnpm` runs a deps check that shells out to `pnpm install`, which exits 1 with
`[ERR_PNPM_IGNORED_BUILDS] Ignored build scripts: unrs-resolver@1.12.2` (pnpm's supply-chain
approval gate). The underlying tools are fine: invoked directly from `apps/web/node_modules/.bin`,
`tsc`, `eslint`, `vitest`, and `next build` all pass, which is what the table above records.

This is pre-existing and unrelated to AUTH-04, which adds **zero** frontend files. The fix is
`pnpm approve-builds` or an `onlyBuiltDependencies` entry in `apps/web/package.json` — a
supply-chain approval decision for a human, not something an agent should make unilaterally.
Recorded as flag **AF-01**.
