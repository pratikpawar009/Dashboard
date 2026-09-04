# AUTH-05 — evidence pass

Six-dimension evidence packet from `/arh-implement` Step 1, run once over the merged tree after all
20 tasks reached `done`. Verdict: **READY on round 1** — no fix loop entered.

Raw captures (`*.log`) sit in this directory but are **not committed** — `.gitignore` excludes
`*.log` repo-wide. This README is the durable record; the structured version lives in
`../state.json` under `.impl_evidence`.

| Dimension | Verdict | Command | Result |
|---|---|---|---|
| typecheck | PASS | `tsc --noEmit` (web) + `uv run mypy .` (api) | web exit 0; api `Success: no issues found in 95 source files` |
| unit_tests | PASS | `vitest run` (web) + `uv run pytest` (api) | web **20 files / 96 tests passed**; api 434 passed (238 pre-existing `on_event` deprecation warnings, unrelated) |
| lint | PASS | `eslint .` (web) + `uv run ruff check .` (api) | web exit 0; api `All checks passed!` |
| runtime | PASS | `uvicorn app.main:app --port 8000` + `pnpm dev --port 3000` | see below |
| compile | PASS | `next build --turbopack` (web); api is interpreted, no compile step | 8/8 static pages; all four new routes present in the build output |
| design_check | **N/A** | — | N/A on two grounds: `project-commands.yaml design_check: ""` (no tool wired) and `state.json design: "n/a"` (no `AUTH` epic in `docs/design/schema.json`; this story ships Route Handlers, a token store and API-client changes with no rendered UI). Flag **AF-04**, triaged `reject` — N/A is correct. |

## What the runtime dimension proved that the unit tests could not

Every frontend test in this story mocks at the `fetch` boundary and mocks `next/headers`, because
jsdom has no implementation of either. The runtime check booted **both real server processes** — a
real uvicorn against the running `dashboard-postgres` container (migrations already at head,
`001_initial_schema`), and a real Next.js dev server — with no mocks anywhere, and exercised the
four routes this story adds:

- `GET /` → 200, boot log clean.
- `GET /login` → 307 (Next's default redirect status for `NextResponse.redirect`; the relay itself
  is exercised in `login/route.test.ts`).
- `GET /callback` → 307.
- `GET /api/proxy/programs` → **401**, and `GET /api/proxy/program-detail/prog-042` → **401**, both
  with no session cookie present. This is the ADR-0008 contract demonstrated against a live stack:
  the proxy resolves the token server-side or refuses, and never returns a token to the browser.

Compile output listed `/login`, `/callback`, `/api/proxy/programs` and
`/api/proxy/program-detail/[program_id]` as real routes, confirming Next's file-path convention
registered all four — the "no wiring gap" claim in PLAN.md § 3, checked rather than assumed.

Stale servers from a prior session were occupying both canonical ports and were killed before the
check, per this project's canonical-ports convention (api 8000, web 3000 — never sidestep a
conflict by picking an alternate port). Port ownership was confirmed with
`lsof -nP -iTCP:<port> -sTCP:LISTEN` before trusting any response, and both servers were torn down
afterwards. The `[ERR_PNPM_IGNORED_BUILDS]` failure recorded against AUTH-04 did not reproduce on
this boot.

## Known limit of the runtime dimension

`render_check` is `unavailable`: `test_e2e` is empty in `docs/config/project-commands.yaml` (no
Playwright or Cypress declared per ADR-0001), so nothing can assert an actual DOM mount beyond a raw
HTTP 200. Recorded as flag **AF-05**, triaged `reject` — AUTH-05 ships no new rendered UI, only a
retrofit of PGD-01's existing components, whose render behaviour is covered by the 96 passing tests
including React Testing Library renders.
