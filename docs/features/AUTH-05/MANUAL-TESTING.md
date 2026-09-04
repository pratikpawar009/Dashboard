# AUTH-05 — manual dev-bypass verification (research condition 2)

Substitutes for E2E (`docs/config/project-commands.yaml`'s `test_e2e:` is empty) and a local
Keycloak (`docker-compose.yml` has none — carry-forward `R-09-no-local-keycloak-e2e`). Verifies
AUTH-05-AC-11 using `POST /auth/dev-bypass` in place of a real OIDC sign-in.

**Coverage limits — read first.** `POST /auth/refresh` (`services/api/app/auth/oidc.py::oidc_refresh`)
always exchanges the token against the real Keycloak endpoint. A dev-bypass-minted `refresh_token`
is a locally-signed JWT Keycloak never issued (`app/auth/dev_bypass.py`: "dev-bypass has no refresh
route of its own to redeem this against") — it can never be exchanged successfully. With
`OIDC_CLIENT_ID`/`OIDC_CLIENT_SECRET` unset (the shipped `.env.example` default), every refresh
attempt 501s before reaching Keycloak; with OIDC fully configured, Keycloak itself rejects the
token (401). Either way: **steps 5 and 6 below can only prove a refresh attempt fires at the right
time and does not loop — not that it succeeds.** A genuinely successful refresh needs a real
Keycloak-issued refresh token (go through `/login` → `/callback` once). Step 7 is unaffected — it
wants a failed refresh, which dev-bypass produces without any extra mocking.

## Setup

1. Backend: `cd services/api && uv run uvicorn app.main:app --reload --port 8000`. Frontend:
   `pnpm -C apps/web dev` (port 3000). Canonical ports — do not substitute.
2. `services/api/.env`'s `ENVIRONMENT` must resolve to one of `local`, `development`, `dev`, `test`,
   `ci` (`app/core/config.py::dev_bypass_enabled`) — the shipped `.env.example` default
   (`ENVIRONMENT=development`) already qualifies. Any other value (a typo, `staging`, unset) means
   `/auth/dev-bypass` was **never registered**: `app/main.py` only calls
   `app.include_router(dev_bypass_router)` when the allow-list matches, so the route 404s. If step 1
   below 404s, check this first — it is a config state, not a bug in this feature.
3. Steps 4-7 all trigger via the **Switch program** control (`apps/web/src/components/ProgramSwitcher.tsx`),
   which renders `disabled` when `GET /api/programs` returns fewer than 2 entries. If it's greyed
   out and doesn't open on click, your local Postgres/persona config isn't surfacing ≥2 programs to
   this session — `curl -H "Authorization: Bearer <access_token>" http://localhost:8000/api/programs`
   to check directly. That's a seed-data/persona concern outside AUTH-05's scope, not something this
   doc's steps can fix.

## Steps

### 1. Mint a token

```
curl -s -X POST http://localhost:8000/auth/dev-bypass \
  -H "Content-Type: application/json" \
  -d '{"role":"cio","email":"manual-test@local"}'
```

**Expected**: `200` with `{"access_token": "...", "refresh_token": "...", "expires_in": 3600}`.
`role: "cio"` is a suggestion so `GET /api/programs` isn't scoped down to `session.programs`
(README § API) — helps step 3's setup note above. A `404` here means the `ENVIRONMENT` allow-list
check failed (Setup step 2), not a code defect.

### 2. Get the token into the cookie; confirm it's httpOnly

There is no UI path from `/auth/dev-bypass` to the cookie — real traffic only reaches
`dashboard_session` via `/callback`'s `writeSession()` (`apps/web/src/app/callback/route.ts`). Build
it by hand:

1. From step 1's response, compute `expiresAt = <now in ms> + expires_in * 1000` (e.g. any page's
   DevTools Console: `Date.now() + 3600000`).
2. Build the cookie value — exactly `StoredSession`'s shape (`apps/web/src/lib/tokenStore.ts`):
   `{"accessToken":"<access_token>","refreshToken":"<refresh_token>","expiresAt":<expiresAt>}`.
3. Open `http://localhost:3000`, DevTools → **Application** → **Cookies** →
   `http://localhost:3000` → add a row: Name `dashboard_session`, Value = the JSON string from (2)
   pasted verbatim, Path `/`, tick **HttpOnly**, leave **Secure** unticked (matches `tokenStore.ts`'s
   `secure: NODE_ENV === "production"`, false under `pnpm dev`), SameSite `Lax`.

**Expected**: the `dashboard_session` row appears with `HttpOnly` ticked. In the **Console**,
`document.cookie` does not contain `dashboard_session` anywhere in its output.

### 3. Server-rendered request carries the bearer token

Reload `http://localhost:3000/programs/<a-real-program-id>`.

**Expected** — this fetch never touches the browser (`page.tsx` runs it server-side via
`fetchProgramDetail` in `@/lib/programDetailApi`), so look in two places, not DevTools' Network tab:
- The `uvicorn` terminal (its default access log) shows `"GET /api/overview/program-detail/<id>
  HTTP/1.1" 200`.
- The page renders the populated header/summary cards, not `ProgramDetailErrorPanel`. Per README's
  documented contract, a `200` only happens when `get_current_user` accepted `Authorization:
  Bearer` — a populated render is proof the header was attached and valid. (A `404 program not
  found` also proves it was accepted, just against an unknown id.)

### 4. Client-proxied request carries the same header — server-to-server only

Click **Switch program**, then a different program row.

**Expected** — the dual-path proof, both at once:
- DevTools → **Network**: a same-origin `GET /api/proxy/program-detail/<new-id>` request. Its
  **Request Headers** carry **no** `Authorization` header at all — the client module
  (`@/lib/programDetailApi.client.ts`) never has a token to attach (D-08/D-10).
- The `uvicorn` terminal, at the same moment: a new `"GET /api/overview/program-detail/<new-id>
  HTTP/1.1" 200` line — the proxy Route Handler's own server-to-server call
  (`apps/web/src/app/api/proxy/program-detail/[program_id]/route.ts`), carrying the real
  `Authorization: Bearer`, invisible to the browser. That contrast (nothing browser-side, everything
  Node-to-FastAPI) is what ADR-0008 buys.

### 5. Proactive refresh fires inside the 60s skew

Edit the cookie from step 2 again: change only `expiresAt` to `Date.now() + 10000` (10s out — inside
`tokenStore.ts`'s `PROACTIVE_REFRESH_SKEW_MS = 60_000`). Leave `accessToken`/`refreshToken`
untouched. Click **Switch program** → pick a row.

**Expected**: the `uvicorn` terminal shows a `"POST /auth/refresh HTTP/1.1"` line **before** any new
`GET /api/overview/program-detail/...` line for the switch target — confirms `ensureTokenValid()`'s
proactive check fired ahead of the call it guards. Per the coverage-limits note above, that refresh
then fails (`501` if OIDC is unconfigured, `401` if Keycloak rejects the dev-bypass token), and the
browser ends up at `/login`, same as step 7 — that failure is expected here; it is the *timing* this
step checks, not the outcome.

If you instead trigger this via a fresh load of `/programs/<id>` rather than the switcher: see
`docs/features/AUTH-05/FLAGS.md` AF-01 — a refresh triggered from `page.tsx`'s Server Component
render cannot persist the refreshed cookie (Next.js seals cookie writes during a plain render), so
even a successful refresh wouldn't show a changed `expiresAt` afterward. This is expected, not a
defect. The switcher's Route Handler path (used above) does not have this limitation.

### 6. Reactive refresh on a 401 — exactly one, not a loop

Repeat steps 1-2 for a fresh cookie (far-future `expiresAt`, e.g. `+3600000`). Edit only
`accessToken`: change 5-6 characters in its payload segment (the middle part, between the two `.`
separators) to garbage, e.g. `XXXXXX` — this breaks the signature without touching `expiresAt`,
isolating the reactive path from step 5's proactive one. Click **Switch program** → pick a row.

**Expected**: the `uvicorn` terminal shows, in order: `"GET /api/overview/program-detail/<id>
HTTP/1.1" 401`, then exactly **one** `"POST /auth/refresh HTTP/1.1"` line. Confirm there is no
second 401 on that GET and no second refresh line — that absence is the "not a loop" guarantee
(`tokenStore.ts::callWithAuth`). Per the coverage-limits note, the refresh itself fails (same reason
as step 5), so the retried request never actually fires — `makeRequest` only runs a second time
after a *successful* refresh, which dev-bypass cannot produce. Confirming the full
retry-then-succeeds path needs a real Keycloak-issued refresh token.

### 7. Failed refresh clears the cookie and lands on `/login`

Repeat steps 1-2 for a fresh cookie. Edit two fields together: `expiresAt` → `Date.now() + 10000`
(forces an immediate refresh attempt, same as step 5) and `refreshToken` → any garbage string (e.g.
append `-corrupted`) so the failure is deterministic even if your environment has OIDC configured.
Click **Switch program** → pick a row.

**Expected**:
- DevTools → Application → Cookies: the `dashboard_session` row is gone after the click
  (`tokenStore.ts::clearSession()` ran inside the proxy Route Handler, where cookie mutation is
  legal — unlike step 5's `page.tsx` caveat, AF-01 does not apply here).
- The browser navigates to `/login` (`ProgramDetailView.tsx::handleSelect`'s
  `window.location.href = "/login"` on an `"unauthorized"` result).

## Coverage summary

| Step | Fully verifiable with dev-bypass alone? |
|---|---|
| 1-4 | Yes |
| 5 | Timing only — refresh fires before the guarded call. Success requires real Keycloak. |
| 6 | "Not a loop" only — exactly one attempt. A successful retry requires real Keycloak. |
| 7 | Yes — dev-bypass refresh tokens are rejected by `/auth/refresh` by construction. |
