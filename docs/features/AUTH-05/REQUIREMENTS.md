# Feature: AUTH-05 — Frontend session/token layer (server-side store, bearer forwarding, refresh)

## Problem

`apps/web` has zero auth code (session contract `frontend_ownership_note`): AUTH-01 shipped
`/auth/login`, `/auth/callback`, `/auth/refresh`, `/auth/dev-bypass` on the FastAPI side, but no
frontend surface stores or forwards a token. `fetchProgramDetail`/`fetchPrograms`
(`apps/web/src/lib/programDetailApi.ts`) call FastAPI with an explicit `// D-08: no Authorization
header` comment on both call sites — the disclosed `frontend-auth-token-gap` carry-forward against
PGD-01. Once any FastAPI route enforces bearer auth, every existing frontend caller breaks, and
today nothing survives a page reload — there is no session at all from the browser's perspective.

## Outcome

A signed-in user's Keycloak-issued tokens live in an httpOnly cookie the frontend's own server
code owns. Every FastAPI call `apps/web` makes — server-rendered or client-triggered — carries
`Authorization: Bearer <access_token>` automatically. Expiry is invisible to the user: proactive
refresh fires at 60s remaining, a stray `401` triggers one reactive refresh + retry, and an
unrecoverable refresh failure routes the user back through Keycloak sign-in rather than surfacing
a raw error. `fetchProgramDetail`/`fetchPrograms` carry a token on every call site, closing
`frontend-auth-token-gap`.

## Constraints

- No `services/api` code change (research Fact 1). `_resolve_redirect_uri`
  (`services/api/app/auth/oidc.py:84`) already reads `settings.oidc_redirect_uri` verbatim when
  set; `OIDC_REDIRECT_URI` already exists blank in `config.py:55` / `.env.example:30`. This
  story's only backend footprint is setting that config value plus two README edits (AC-12/13).
- `frontend_storage` (session contract) pins the token store to the httpOnly-cookie option, not
  in-memory — RTM Decision 2026-09-04, CONFIRMED by user.
- `/auth/callback` returns a JSON body only, never a redirect or `Set-Cookie` (session contract
  `mechanism`) — the frontend's own `/callback` Route Handler is the only place a `Set-Cookie` for
  this feature can originate.
- D-13/D-14 hold: `state` and the PKCE `code_verifier` live in FastAPI's own in-memory store
  (`app/auth/state_store.py`), keyed by the opaque `state` string, independent of which origin the
  browser's requests touch — the frontend's server-to-server relay of `code`/`state` completes
  identically to a direct browser call. Not a risk this story must mitigate.
- No local Keycloak in `docker-compose.yml` (carry-forward `R-09-no-local-keycloak-e2e`);
  `POST /auth/dev-bypass` is the only local verification path (AC-11).
- `test_e2e` is empty in `docs/config/project-commands.yaml` — no browser-level login test is
  runnable; `vitest` is the only frontend test runner (research Testability finding).
- A client component cannot read an httpOnly cookie via `cookies()` (Next.js 15, async,
  server-only). `ProgramDetailView.tsx` is a client component that calls `fetchPrograms()` and
  `fetchProgramDetail()` directly today — those calls cannot attach a bearer token without an
  intermediate same-origin proxy (research risk #2, HIGH; see FR-2).

## Solution sketch

Two new Next.js Route Handlers, `/login` and `/callback`, relay the OAuth handshake
server-to-server to FastAPI's already-shipped `/auth/login`/`/auth/callback`, so the browser only
ever talks to the frontend's own origin; Keycloak is told to redirect back to `/callback`, not to
FastAPI. A new `tokenStore` module owns the httpOnly cookie holding the `{access_token,
refresh_token, expires_in}`-derived state, exposes a single-flight-guarded `ensureTokenValid()`
used by both a proactive 60s-skew check and a reactive `401` handler, and clears the cookie plus
redirects to `/login` on any unrecoverable refresh failure. Server Components (`page.tsx`) read
the cookie directly; the one existing client component (`ProgramDetailView`) and any future
client-side caller reach FastAPI only through this same Route Handler layer, never directly.
`fetchProgramDetail`/`fetchPrograms` are retrofitted in one pass to attach the resulting bearer
token via D-08's additive `opts` parameter.

## Addressing Research Conditions

Research verdict GO-WITH-CONDITIONS (79/100). `docs/research/AUTH-05.md` line 224, all 5:

1. **Single-flight refresh guard** — mitigated by FR-1: `tokenStore.ts` implements a
   `Promise`-based `ensureTokenValid()` guard (one `refreshPromise` in flight at a time; concurrent
   callers await the same promise rather than issuing parallel `POST /auth/refresh` calls). A
   dedicated concurrent-refresh test (two parallel triggers resolve to exactly one refresh call) is
   a required Phase-2 test case, not optional coverage.
2. **Manual-test steps for dev-bypass** — mitigated: concrete steps (1) `POST /auth/dev-bypass
   {role, email}` with `ENVIRONMENT=local` to mint a token; (2) confirm the httpOnly cookie is set
   and unreadable via `document.cookie`; (3) load `/programs/{id}` and confirm the server-rendered
   request carries `Authorization: Bearer`; (4) trigger the switcher and confirm the same header on
   the Route-Handler-proxied client request; (5) force the stored expiry inside the 60s skew window
   and confirm a proactive refresh fires before the next call; (6) force a `401` and confirm one
   reactive refresh + one retry, not a loop; (7) mock a non-2xx `/auth/refresh` response and confirm
   the cookie clears and the browser lands on `/login`. These carry into `/arh-plan-implementation`
   as the story's manual-test task, matching the story's own Test Mapping § Manual.
3. **Keycloak client registration as a deploy prerequisite** — mitigated: Rollout plan names it a
   blocking pre-deploy step, not a post-deploy follow-up; Documentation requirements (AC-13) adds
   the additive bullet to README § Keycloak client requirements.
4. **Audit all log lines for token values** — mitigated by the Security NFR: a dedicated log-audit
   test asserts no emitted log record (token store, `/login`, `/callback`, refresh path) contains a
   JWT-shaped substring (the `eyJ` header prefix), extending AUTH-01's `user_id`-only invariant.
5. **All `fetchProgramDetail()`/`fetchPrograms()` call sites updated in one pass** — mitigated by
   FR-2, which enumerates every known call site (`page.tsx` server-side; `ProgramDetailView.tsx`'s
   two client-side call sites) and requires the retrofit to land as one change, not phased —
   reflected in the Rollout plan's bang-bang strategy.

## Scope

**In:**
- `/login` and `/callback` Next.js Route Handlers relaying server-to-server to FastAPI's
  `GET /auth/login` / `GET /auth/callback`.
- `tokenStore.ts`: httpOnly cookie read/write, expiry tracking from `expires_in`, single-flight
  guarded proactive (60s skew) + reactive (`401`) refresh, non-2xx-refresh → clear cookie + redirect
  to `/login`.
- `fetchProgramDetail`/`fetchPrograms` retrofit: `Authorization: Bearer` via `opts.accessToken`,
  wired at every call site (`page.tsx`, `ProgramDetailView.tsx` ×2) in one pass.
- `OIDC_REDIRECT_URI` set to the frontend's callback route in deployment config.
- `README.md`: `OIDC_REDIRECT_URI` env-var row (AC-12); Keycloak client requirements bullet for the
  additional redirect URI (AC-13).
- Manual verification path via `POST /auth/dev-bypass` (no local Keycloak).

**Out:**
- Any `services/api` code change — `OIDC_REDIRECT_URI` is a config value only (Constraints).
- A sign-out/logout flow — no AC requests one; the cookie is cleared only on unrecoverable refresh
  failure (AC-8).
- Live Keycloak E2E testing — `test_e2e` is empty; blocked by `R-09-no-local-keycloak-e2e`.
- Changing FastAPI's CORS allow-list — FR-2 flags the consequence for the implementation plan to
  verify, but no CORS config edit is performed by this story.
- Preserving the originally-requested page across the AC-8 forced re-login redirect — the user
  lands at `/login`'s own post-auth destination, not back at the specific page they were viewing.
- SHP-01/PGD-01 UI or visual changes — this story only wires `opts.accessToken` into an existing
  interface; no component markup changes.

## Functional requirements

FRs trace 1:1 to story ACs; see `docs/stories/AUTH-05.md` for canonical wording.
New impl constraints introduced below:

**AUTH-05-FR-1** — Single-flight refresh guard *(extends AC-6/AC-7 with: concurrency control)*

`tokenStore.ts` holds one module-level `refreshPromise: Promise<TokenResponse> | null`. Any caller
needing a valid token — the proactive 60s-skew check or the reactive `401` handler — calls
`ensureTokenValid()`: if `refreshPromise` is set, it awaits that same promise; otherwise it starts
`doRefresh()`, assigns the promise, and clears it in a `finally`. Exactly one `POST /auth/refresh`
call is ever in flight regardless of how many callers trigger it concurrently (research condition
1, `.claude/rules/performance-baseline.md`).

**AUTH-05-FR-2** — Client-side calls proxy through a Route Handler; server-side calls read the
cookie directly *(extends AC-5/AC-10 with: the two call paths this story introduces, and their
retrofit)*

`page.tsx` is a Server Component: it reads the httpOnly cookie directly via `cookies()` and calls
`fetchProgramDetail` server-side with the resulting `opts.accessToken`. `ProgramDetailView.tsx` is
a client component (`"use client"`) and cannot read an httpOnly cookie — its calls to
`fetchPrograms()` and `fetchProgramDetail()` (including the switcher's follow-up call) must resolve
`opts.accessToken` through a same-origin Route Handler that reads the cookie server-side and either
proxies the FastAPI call or hands back the token for the client to attach itself. Both call paths
are retrofitted in the same change (research condition 5) — `page.tsx`'s single call site and
`ProgramDetailView.tsx`'s two call sites (initial `fetchPrograms()` in `useEffect`, and the
switcher's `fetchProgramDetail(newId, { switchedFrom, accessToken })`) all pass a non-empty
`accessToken` after this story, with none left on the pre-AUTH-05 unauthenticated path.

**Flagged consequence (not fixed by this story):** PGD-01 added `X-Program-Switch-From` to
FastAPI's CORS `allow_headers` (`services/api/app/main.py:72-78`) specifically because
`ProgramDetailView` called FastAPI directly from the browser. Once that call routes through the
Route Handler proxy instead, the Route Handler's own fetch to FastAPI is server-to-server —
CORS never applies to it. This story does not remove or edit the existing CORS allow-list entry
(other callers may still exist), but the implementation plan must verify whether any caller still
performs a direct browser-to-FastAPI request after this retrofit; if none does, the CORS entry
becomes dead configuration for a future story to clean up, not this one.

**AUTH-05-FR-3** — Route Handler paths pinned to `/login` and `/callback` *(extends AC-2/AC-3 with:
exact file location)*

The story's ACs name the routes `/login` and `/callback` literally (not `/api/auth/login` /
`/api/auth/callback`, which appear only in the research doc's illustrative Pattern Map, not in any
RTM Decision). Since `OIDC_REDIRECT_URI`'s assumed value (`http://localhost:3000/callback`, story
Decision log) must exact-match the route Keycloak redirects to, the two Route Handlers live at
`apps/web/src/app/login/route.ts` and `apps/web/src/app/callback/route.ts` — top-level routes, not
nested under an `/api/auth/` prefix. No existing page occupies either path (research: no
`src/app/login` or `src/app/callback` exists today).

**AUTH-05-FR-4** — httpOnly cookie shape *(extends AC-4 with: cookie name and attributes)*

The cookie is named `dashboard_session` and set with `httpOnly: true`, `sameSite: "lax"`,
`secure: true` outside a local/development environment, `path: "/"`, and no explicit `maxAge`
(session-scoped — cleared explicitly on an unrecoverable refresh failure per AC-8, not on a timer)
— assumption; the session contract's `frontend_storage` field mandates the httpOnly-cookie
mechanism but not these exact flags, so this follows `.claude/rules/security-baseline.md`'s
session-cookie guidance (`Secure` + `HttpOnly` + `SameSite=Lax|Strict`) rather than a story-given
value.

**AUTH-05-FR-5** — Refresh-failure redirect target *(extends AC-8 with: exact redirect chain)*

On a non-2xx `/auth/refresh` response, the frontend clears the `dashboard_session` cookie and
302s the browser to its own `/login` Route Handler (FR-3) — not directly to Keycloak. `/login`
then runs the same server-to-server relay a fresh sign-in uses (AC-2), so the browser's own
redirect is a single hop; the subsequent hop to Keycloak is `/login`'s own logic. No return-URL
parameter is preserved across this redirect — assumption, since no AC requests one; the user lands
at `/login`'s default post-auth destination, not back at the page they were viewing.

## Non-functional requirements

- Performance: Per `.claude/rules/performance-baseline.md`: every server-to-server call (the
  `/login`/`/callback` relay and both refresh paths) carries an explicit `5000ms` timeout —
  assumption, matching `programDetailApi.ts`'s existing `FETCH_TIMEOUT_MS` precedent (no
  story-specific budget given). Refresh calls are single-flight guarded (FR-1) — no unbounded
  fan-out of concurrent `POST /auth/refresh` calls. No new user-facing latency budget: this
  story's server-to-server work runs on the frontend's own Node process, not an added round trip
  the user waits on beyond AUTH-01's existing NFR-002 2s range-refresh budget.
- Security: Per `.claude/rules/security-baseline.md`: applies to `/login`, `/callback`, the token
  store, and the `programDetailApi.ts` retrofit. Feature-specific: access/refresh tokens exist only
  in the `dashboard_session` httpOnly cookie (FR-4) — never `localStorage`, `sessionStorage`, or a
  client-JS-readable cookie. No log line, frontend or backend, includes a token value — extends
  AUTH-01's `dashboard_login` `user_id`-only invariant to this story's own store/redirect code
  (research condition 4); enforced by a dedicated test asserting no emitted log record across the
  token store, `/login`, `/callback`, or refresh path contains a JWT-shaped substring (the `eyJ`
  header prefix).
- Accessibility: N/A — this story ships Route Handlers, a server-side token store, and API-client
  changes, with no rendered UI (`design: n/a`; `docs/design/schema.json`'s
  `designSystem.pages.features` has no `AUTH` key — confirmed, only `OVW, PGD, EMD, ARC, DEV, PMD`
  exist). The Keycloak-hosted login page's own accessibility is scoped to AUTH-01/the IdP.
- Observability: No new backend log event — this story's only `services/api` touch is a config
  value (`OIDC_REDIRECT_URI`), not code. The session contract's `observability` invariant
  (`dashboard_login` carries `user_id` only, never token values) extends to the frontend's own
  store/redirect code paths — no frontend log line may include a token value either (assumption,
  same precedent as AUTH-01's NFR; covered by the Security NFR's log-audit test above).

## Visual spec

Not applicable — this story ships Route Handlers, a server-side token store, and API-client
changes, with no rendered UI. `docs/design/schema.json`'s `designSystem.pages.features` covers
`OVW, PGD, EMD, ARC, DEV, PMD` only — no `AUTH` epic exists, which is CLAUDE.md's stated escape for
`design: n/a` ("Only a story with no epic in `schema.json` may set `design: n/a`", confirmed by
direct read of `schema.json`). `integrations.design` remains `html-mockup` at the project level;
this is a documented per-story override, not a project-wide absence of the design provider.

## Rollout plan

- **Strategy**: bang-bang — additive Route Handlers plus a same-pass retrofit of the two existing
  API-client functions; low blast radius, no phased cohort needed. Research condition 5 requires
  the retrofit to land whole rather than phased, since a partial retrofit would leave some callers
  silently unauthenticated once auth is enforced upstream.
- **Feature flag**: none — the existing `OIDC_CLIENT_ID`/`OIDC_CLIENT_SECRET`/`OIDC_ISSUER` triple
  is already the feature flag gating whether `/auth/login`/`/auth/callback` are live (session
  contract `config_completeness_gate`); this story adds no new flag.
- **Backout plan**: revert the `/login`/`/callback` Route Handlers and the `opts.accessToken`
  wiring in `programDetailApi.ts`; unset `OIDC_REDIRECT_URI` to fall back to the API's own callback
  default (README, AC-1). No schema or data migration to unwind.
- **Success signal**: Keycloak client registration confirmed (condition 3) and a real
  (non-dev-bypass) sign-in completes end-to-end in a deployed environment, with zero `401`s on
  `fetchProgramDetail`/`fetchPrograms` attributable to a missing bearer header, over the first
  successful session after deploy.

## Documentation requirements

- **README updates**: `README.md` § Environment variables — add an `OIDC_REDIRECT_URI` row (AC-12,
  frontend-callback value, notes the unset-fallback to the API's own callback). `README.md` §
  Keycloak client requirements — add a bullet stating the frontend's callback URL must be
  registered as an **additional** valid redirect URI, extending (not replacing) the existing
  API-origin requirement (AC-13).
- **Runbook**: none.
- **API reference**: none — no new `services/api` routes; FastAPI's existing `/docs` already
  covers `/auth/*`.
- **Inline code comments**: `tokenStore.ts` module docstring documenting the single-flight guard
  (FR-1) and the refresh-failure redirect chain (FR-5); `login/route.ts` and `callback/route.ts`
  documenting the server-to-server relay contract (no client-side page ever parses the callback
  response); `programDetailApi.ts` — remove the now-stale `// D-08: no Authorization header`
  comments at both call sites once the header is wired.
- **Examples / how-to**: none.

## Open questions

Decisions logged in `docs/stories/AUTH-05.md` § Decision log.

## Approvals

| Role | Reviewer | Date | Verdict |
|---|---|---|---|
| Product Owner | Pratik Pawar (pratik.pawar@apexon.com) | 2026-09-04 | APPROVE |
| Designer | — | — | N/A — `design_mode = none`; no `AUTH` epic in `docs/design/schema.json` and this story ships no rendered UI |
| BA | Pratik Pawar (pratik.pawar@apexon.com) | 2026-09-04 | APPROVE — test cases reviewed for completeness and automation feasibility (4/4 automatable under `vitest`) |

### Accepted at gate: test-case coverage gap

`docs/test-cases/AUTH-05.json` `coverage_audit.uncovered` is **non-empty** —
`AUTH-05-AC-12` and `AUTH-05-AC-13` have no backing test case. Approved anyway, deliberately:

- The user set a hard cap of 3–4 test cases for this run. The four cases were spent on the four
  HIGH risks the research register ranked (single-flight refresh guard, dual-path bearer
  forwarding, token-leak prevention, refresh-failure redirect).
- AC-12 (`OIDC_REDIRECT_URI` row in README's env-var table) and AC-13 (the Keycloak
  client-requirements bullet for the additional valid redirect URI) are **documentation-only
  edits with no runtime behaviour** — there is nothing for an automated case to execute.
- Both are verifiable by inspecting the README diff at `/arh-review`. That is the agreed
  verification route, recorded here so the gap is not rediscovered as a defect later.

Trading a HIGH-risk case for a README-diff assertion would have been the worse deal.
