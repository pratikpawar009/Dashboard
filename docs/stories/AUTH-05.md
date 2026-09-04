# Story: AUTH-05 — Frontend session/token layer (server-side store, bearer forwarding, refresh)

**Epic**: AUTH
**Status**: Validated
**Priority**: P1
**Owner**: —
**Updated**: 2026-09-04
**Tracker**: pratikpawar009/Dashboard#204 (https://github.com/pratikpawar009/Dashboard/issues/204)
**Tracker Research**: pratikpawar009/Dashboard#205 (https://github.com/pratikpawar009/Dashboard/issues/205)
**Tracker Plan Requirements**: pratikpawar009/Dashboard#206 (https://github.com/pratikpawar009/Dashboard/issues/206)
**Tracker Plan Implementation**: pratikpawar009/Dashboard#211 (https://github.com/pratikpawar009/Dashboard/issues/211)

## User story

As a signed-in dashboard user, I want the frontend to hold my Keycloak-issued tokens server-side and forward them to every backend call automatically, so that I stay signed in across page loads and API calls without the browser or client-side JavaScript ever touching a token.

## Acceptance criteria

1. Given deployment configuration, when `OIDC_REDIRECT_URI` is inspected, then it is set to the frontend's own callback route (e.g. `http://localhost:3000/callback` locally) rather than left blank (which falls back to the API's own `/auth/callback` default, `services/api/app/auth/oidc.py::_resolve_redirect_uri`).
2. Given a user initiates sign-in, when the frontend's `/login` Route Handler calls FastAPI's `GET /auth/login` server-to-server with a non-following redirect, then it relays the captured Keycloak authorization URL to the browser — the browser navigates to Keycloak directly, never to FastAPI.
3. Given Keycloak redirects the browser back to the frontend's `/callback` route with `code` and `state`, when that Route Handler runs, then it relays `code`/`state` server-to-server to FastAPI's existing `GET /auth/callback`, receives `{access_token, refresh_token, expires_in}`, and 302s the browser onward to the originally requested page — no client-side page ever parses the callback response.
4. Given the callback exchange in AC-3 succeeds, when the frontend stores the returned tokens, then it writes them to an httpOnly cookie scoped to the frontend's own origin — never `localStorage`, `sessionStorage`, or a client-JS-readable cookie.
5. Given the httpOnly cookie holds a valid access token, when the frontend's server-side code calls any FastAPI route, then it attaches `Authorization: Bearer <access_token>` to that request.
6. Given the stored access token has 60 seconds or less remaining before its `expires_in`-derived expiry, when the frontend is about to make the next FastAPI call, then it proactively calls `POST /auth/refresh` with the refresh token first and stores the new pair before proceeding.
7. Given a FastAPI call returns `401` without having been proactively refreshed, when the frontend's server-side store handles it, then it reactively calls `POST /auth/refresh` and retries the original call once with the new access token.
8. Given `POST /auth/refresh` itself returns a non-2xx response, when the frontend observes it, then it clears the stored cookie and redirects the user back through the Keycloak login flow (`/login`) rather than surfacing the raw error.
9. Given a token response with any `expires_in` value, when the frontend schedules its next proactive-refresh check, then it uses that response's own `expires_in` — never a hardcoded lifetime constant.
10. Given `apps/web/src/lib/programDetailApi.ts`'s `fetchProgramDetail` and `fetchPrograms`, when either is called, then it attaches `Authorization: Bearer <access_token>` sourced from the frontend's server-side store via the existing additive `opts` parameter (D-08) — closing the `frontend-auth-token-gap` carry-forward recorded against PGD-01.
11. Given no local Keycloak instance exists (`docker-compose.yml` has none; carry-forward `R-09-no-local-keycloak-e2e`), when a developer verifies this flow locally, then they mint a token via `POST /auth/dev-bypass` (same `{access_token, refresh_token, expires_in}` Bearer shape) and confirm it is stored and forwarded exactly as a Keycloak-issued token would be.
12. Given `README.md`'s Environment-variables table, when inspected after this story, then it includes an `OIDC_REDIRECT_URI` row documenting the frontend-callback value and that leaving it unset falls back to the API's own callback URL.
13. Given `README.md`'s "Keycloak client requirements" section, when inspected after this story, then it includes an added bullet stating the frontend's callback URL must be registered as an **additional** valid redirect URI on the Keycloak client — extending, not contradicting, the existing sentence that the API's own callback remains required and non-interchangeable.

## Non-functional requirements

- Performance: N/A — no new user-facing latency budget. The `/login`/`/callback` relay and the proactive/reactive refresh run server-to-server on the frontend's own Node process, not an added round trip the user waits on beyond NFR-002's existing 2s range-refresh budget (AUTH-01). Server-to-server relay and refresh calls carry an explicit `5000ms` timeout — assumption, matching `apps/web/src/lib/programDetailApi.ts`'s existing `FETCH_TIMEOUT_MS` precedent (no story-specific budget given; `.claude/rules/performance-baseline.md` requires an explicit timeout on every I/O call).
- Security: access and refresh tokens exist only in the frontend's httpOnly cookie, scoped to the frontend's own origin — never `localStorage`, `sessionStorage`, or a client-JS-readable cookie (session contract `frontend_storage`, resolved to the httpOnly-cookie option per RTM Decision 2026-09-04). No log line, frontend or backend, ever includes a token value — extends AUTH-01's `dashboard_login` invariant (`user_id` only) to this story's own refresh/redirect code paths.
- Accessibility: N/A — this story ships Route Handlers, a token store, and API-client changes; no rendered UI (`design: n/a`, no `AUTH` key in `docs/design/schema.json`). The Keycloak-hosted login page's own accessibility is scoped to AUTH-01/the IdP, not this story.
- Observability: no new backend log event — this story's code is entirely frontend + config, and its only `services/api` touch is a config value (`OIDC_REDIRECT_URI`), not code. Assumption: the session contract's `observability` invariant (`dashboard_login` carries `user_id` only, never token values) extends to the frontend's own store/redirect code — no frontend log line may include a token value either.

## Dependencies

- Upstream: AUTH-01 via `session` contract (`docs/requirements/auth.md#session`) — the shipped `/auth/login`, `/auth/callback`, `/auth/refresh`, `/auth/dev-bypass` routes and their `{access_token, refresh_token, expires_in}` JSON response shape.
- Downstream: SHP-01 and PGD-01 — shipped consumers whose `fetch` calls become authenticated (PGD-01's `frontend-auth-token-gap` carry-forward closes here, AC-10). Every future frontend story that calls a protected FastAPI route depends on this story's token store and bearer-forwarding.

## Test mapping

- E2E: N/A — `test_e2e` is empty in `docs/config/project-commands.yaml` (no Playwright/Cypress installed); a browser-level Keycloak-redirect login test is not currently runnable.
- Unit: `apps/web`'s `/login` and `/callback` Route Handlers, the server-side token store, and the refresh-trigger logic (proactive skew + reactive 401 + non-2xx redirect); `apps/web/src/lib/programDetailApi.ts`'s `fetchProgramDetail`/`fetchPrograms` bearer-attachment. No new `services/api` unit surface — this story's only backend touch is a config value, not code.
- Manual: local verification via `POST /auth/dev-bypass` (no local Keycloak in `docker-compose.yml`, carry-forward `R-09-no-local-keycloak-e2e`) — mint a dev-bypass token, confirm it lands in the httpOnly cookie and is forwarded as `Authorization: Bearer` on `fetchProgramDetail`/`fetchPrograms`.

## Clarifications

None open.

## Decision log

- 2026-09-04 Frontend hand-off mechanism (`/login` + `/callback` Route Handlers, server-to-server relay to FastAPI's existing `/auth/login`/`/auth/callback`): per RTM Decisions 2026-09-04 (RESOLVED, supersedes the earlier open question) — CONFIRMED by user.
- 2026-09-04 `OIDC_REDIRECT_URI` is a config value only, no `services/api` code change (`_resolve_redirect_uri` already reads it verbatim when set): per RTM Decisions 2026-09-04 / session contract `frontend_ownership_note`.
- 2026-09-04 Token storage resolved to httpOnly cookie scoped to the frontend's own origin, not in-memory: per RTM Decisions 2026-09-04 (RESOLVED) Token storage / session contract `frontend_ownership_note`.
- 2026-09-04 Refresh: 60s-remaining proactive skew + reactive 401 + non-2xx-from-refresh → Keycloak-login redirect: per session contract `refresh` field.
- 2026-09-04 Access-token lifetime never hardcoded — implementation always reads `expires_in`: per session contract `refresh` field, same precedent as AUTH-01's NFR.
- 2026-09-04 Reactive-refresh retry count (AC-7): retry the original call once after a successful refresh, not a bounded retry loop — assumption; the session contract's `refresh` field describes triggering a refresh reactively on `401` but doesn't specify retry semantics for the original call.
- 2026-09-04 Local verification via `POST /auth/dev-bypass` in lieu of a live Keycloak redirect: per README's "no local Keycloak" gap (`docker-compose.yml` carry-forward `R-09-no-local-keycloak-e2e`).
- 2026-09-04 Server-to-server relay/refresh timeout: `5000ms` — assumption, matching `apps/web/src/lib/programDetailApi.ts`'s existing `FETCH_TIMEOUT_MS`; no story-specific budget given, but `.claude/rules/performance-baseline.md` requires an explicit timeout on every I/O call.
- 2026-09-04 Illustrative local frontend callback URL (`http://localhost:3000/callback`, AC-1) — assumption, based on `docker-compose.yml`'s frontend port mapping (`3000:3000`) and the `/callback` route name sourced above; the real per-environment value is a deployment choice this story doesn't fix, same non-committal pattern README already uses for the API's own `http://localhost:8000/auth/callback`.
- 2026-09-04 `frontend-auth-token-gap` (PGD-01) closed by retrofitting `fetchProgramDetail`/`fetchPrograms` via D-08's additive `opts` param: per RTM Decisions 2026-09-04 "Carry-forward closure verified per-record."
- 2026-09-04 README additions (env-var row + Keycloak-client-requirements bullet, AC-12/AC-13) are additive, not contradicting the existing "not interchangeable" sentence — the new bullet documents an *additional* valid redirect URI; the API-origin one stays required: per RTM Decisions 2026-09-04 (RESOLVED) + task instruction.
