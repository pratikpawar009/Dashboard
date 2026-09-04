# AUTH-05 — Data Design

State & data management for the frontend session/token layer. Each concern is specified or marked
`N/A — <reason>`. No relational/document schema change anywhere in this story (`services/api`'s
only touch is a config value, DECISIONS.md D-06) — every concern below is about the frontend's own
ephemeral session state and the new Route Handler interfaces.

## 1. Data model

`N/A — no persistent-store entity`. The access/refresh token pair is not modeled as a table or
document row anywhere: Keycloak (or `POST /auth/dev-bypass`) is the source of truth for the tokens
themselves, and the frontend only *carries* them, non-durably, in the httpOnly cookie described in
§7. There is no ORM model, migration, or collection to define.

## 2. Migrations

`N/A — no schema change`. `services/api`'s only edit is the `OIDC_REDIRECT_URI` value in
`.env.example` (DECISIONS.md D-06), not a code or schema change (Constraints, research Fact 1).

## 3. Ownership & tenancy

No new server-side owned resource is created. The `dashboard_session` cookie is scoped by the
browser's own same-origin cookie jar — one browser profile holds at most one session, and
`httpOnly` makes it unreadable to any script regardless of origin. The real authorization
enforcement is unchanged and pre-existing: FastAPI's `get_current_user` dependency (AUTH-01)
validates the bearer JWT signature per request against Keycloak's JWKS; this story adds no new
authorization check, only the transport that gets a valid token attached to requests that were
previously sent with none (PGD-01 D-08, closed here).

## 4. Data classification & retention

`access_token`/`refresh_token` are security-sensitive credentials (not classic PII, but treated
with the same never-logged discipline as one — `.claude/rules/security-baseline.md`). No
server-side persistent storage or retention: the tokens live only in the browser's `dashboard_session`
cookie, cleared explicitly on an unrecoverable refresh failure (AC-8) — no fixed cookie `maxAge`
(FR-4, session-scoped, not timer-cleared) and no server-side copy retained anywhere (no cache, no
DB row, no log line — TC-03). Encryption at rest is `N/A` (nothing is persisted at rest by this
story); transport confidentiality relies on `Secure` (HTTPS-only outside local/dev, FR-4) and
`HttpOnly` (JS-unreadable) cookie attributes, both already required by
`.claude/rules/security-baseline.md`'s session-cookie guidance.

## 5. Consistency & concurrency

FR-1's single-flight guard (`tokenStore.ts`'s module-level `refreshPromise`) is the concurrency
control: any number of concurrent callers needing a valid token (the proactive 60s-skew check, the
reactive 401 handler) collapse into exactly one in-flight `POST /auth/refresh` call — later callers
await the same promise rather than issuing their own (TC-01). This is a per-Node-process guard, not
cross-process (DECISIONS.md D-07) — acceptable because the cookie write itself, not the guard, is
the actual write serialization point, and a multi-process race produces at most one extra refresh
call, never a torn/inconsistent stored token (the cookie's `Set-Cookie` on each response is the
last-writer-wins outcome per process, and `expires_in` is always read fresh from that specific
response — AC-9).

## 6. Caching

The `dashboard_session` cookie value is effectively a client-held cache of Keycloak's (or
dev-bypass's) most recently issued token pair. Cache key: the fixed cookie name
`dashboard_session` (one entry per browser session, no parameterization). TTL: the response's own
`expires_in`, tracked as an absolute `expiresAt` computed at write time (DECISIONS.md D-01) — never
a hardcoded constant (AC-9). Invalidation events: (a) a successful proactive or reactive refresh
overwrites the cookie with the new pair, immediately after that `POST /auth/refresh` response is
received — no batching, no async delay; (b) a non-2xx `/auth/refresh` response clears the cookie
synchronously, before the redirect to `/login` is issued (AC-8) — no window where a stale/dead
token remains stored after the clearing decision is made.

## 7. Ephemeral / session state

The `dashboard_session` httpOnly cookie is this story's only state surface — a browser-held,
non-durable session credential (`next/headers`'s `cookies()` API, read/write only from Server
Components/Route Handlers). Shape: `JSON.stringify({ accessToken, refreshToken, expiresAt })`
(DECISIONS.md D-01). Attributes: `httpOnly: true`, `sameSite: "lax"`, `secure: true` outside
local/development, `path: "/"`, no `maxAge` (FR-4). Lifecycle: written by `/callback` on a
successful OAuth exchange and by `tokenStore.ensureTokenValid()` on every successful refresh;
cleared by `tokenStore.ensureTokenValid()` on an unrecoverable refresh failure (AC-8). No other
client-side or server-held ephemeral state is introduced — `ProgramDetailView.tsx`'s existing
component-local React state (switch-in-flight, switcher open/closed, PGD-01) is untouched by this
story.

## 8. Query-path & access-path performance

No database access path is introduced. The relevant cost axis is outbound-call fan-out on the
frontend's own Node process: every server-to-server relay (`/login` → FastAPI `GET /auth/login`,
`/callback` → FastAPI `GET /auth/callback`, `tokenStore`'s refresh → FastAPI `POST /auth/refresh`)
carries an explicit `AbortSignal.timeout(5000)` (matching `programDetailApi.ts`'s existing
`FETCH_TIMEOUT_MS` precedent, `.claude/rules/performance-baseline.md`'s "explicit timeout on every
I/O call"). FR-1's single-flight guard (§5) is the fan-out control for the highest-frequency call
(`POST /auth/refresh`) — without it, N concurrent requests near the 60s skew would each fire their
own refresh call, an unbounded-fan-out violation of the same rule.

## 9. Contract (API / interface)

Feature-internal — none of these four routes is a registered cross-story contract in
`docs/requirements/*.md` (no `produced_by`/`consumed_by` entry names them; the shared `session`
contract in `docs/requirements/auth.md#session` covers FastAPI's `/auth/*` routes, already filled
at requirements time, unmodified by this plan). Described inline:

- **`GET /login`** (`apps/web/src/app/login/route.ts`) — no request. Relays to FastAPI
  `GET /auth/login` server-to-server with `redirect: "manual"`; response: `302` to the captured
  Keycloak authorization URL. `501`/error from FastAPI (OIDC not configured) surfaces as a generic
  frontend error, never a raw FastAPI body.
- **`GET /callback`** (`apps/web/src/app/callback/route.ts`) — query: `code?`, `state?`, `error?`
  (forwarded verbatim from Keycloak's redirect). Relays to FastAPI `GET /auth/callback`
  server-to-server; on FastAPI `200`, writes the `dashboard_session` cookie (§7) and responds `302`
  to `/` (DECISIONS.md D-04); on any FastAPI non-200, responds `302` to `/login` — no cookie
  written, no raw error body surfaced.
- **`GET /api/proxy/programs`** (`apps/web/src/app/api/proxy/programs/route.ts`) — no request
  besides the `dashboard_session` cookie (ADR-0008 / DECISIONS.md D-09/D-10, full request-proxy).
  Reads the cookie, resolves a valid token via `tokenStore.getValidAccessToken()`, calls the
  server-side `fetchPrograms()` wrapped in `tokenStore.callWithAuth()` (reactive-401 retry-once,
  D-03), and returns `200 {programs: [...]}` or, on an unrecoverable `SessionExpiredError`,
  `401 {error: "session_expired"}`. No token is ever present in the response body or a
  browser-readable header. Consumed only by `ProgramDetailView.tsx`'s `programDetailApi.client.ts`
  (D-08).
- **`GET /api/proxy/program-detail/{program_id}`**
  (`apps/web/src/app/api/proxy/program-detail/[program_id]/route.ts`) — request: path param
  `program_id`, optional `X-Program-Switch-From` header (forwarded verbatim to FastAPI
  server-to-server — the one place this header still travels anywhere in this story, never subject
  to CORS since neither hop is cross-origin, D-11). Same cookie/token/`callWithAuth` mechanics as
  the programs proxy above. Response: `200` (the program detail body), `404` (not found), `401`
  (`session_expired`), or `502` (FastAPI-side error). Consumed only by `ProgramDetailView.tsx`'s
  `programDetailApi.client.ts` (D-08).

## 10. Async & messaging

`N/A` — every call in this story is synchronous request/response HTTP (browser↔frontend,
frontend↔FastAPI). No queue, topic, or background job is introduced.
