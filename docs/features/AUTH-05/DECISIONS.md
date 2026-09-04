# AUTH-05 — Decisions

Decision log for the frontend session/token layer. D-02 is the single highest-leverage call in
this plan — it resolves REQUIREMENTS.md FR-2's explicit either/or ("either proxies the FastAPI
call or hands back the token for the client to attach itself") and settles the CORS-dead-config
question FR-2 flags as unresolved. Every other entry is an implementation-planning decision made
while designing `tokenStore.ts` and the two/three new Route Handlers.

### D-01: `dashboard_session` cookie is one JSON-serialized value, not split fields · blast:feature · rev:mechanical · adr:—

**Context**: FR-4 pins the cookie name (`dashboard_session`) and flag set (`httpOnly`, `sameSite:
"lax"`, `secure` outside local/dev, `path: "/"`, no `maxAge`) but not its internal encoding.
`tokenStore.ts` needs to carry three values — `access_token`, `refresh_token`, and a computed
absolute expiry — under that one cookie name.

**Decision**: The cookie value is `JSON.stringify({ accessToken, refreshToken, expiresAt })`,
where `expiresAt = Date.now() + expires_in * 1000` is computed once at write time (AC-9: the
stored deadline is always derived from the response's own `expires_in`, never a hardcoded
constant). `readSession()` parses and returns `null` on any parse failure (malformed/absent
cookie), never throws — a corrupt cookie is treated identically to "no session", which routes the
caller into the existing sign-in path rather than crashing.

### D-02: Client-side calls resolve a bearer token via a token-vending Route Handler, not a full request-proxy · blast:system · rev:medium · adr:ADR-0008 · **SUPERSEDED by D-10**

**Context**: `ProgramDetailView.tsx` cannot read the httpOnly cookie (client component). FR-2
leaves the mechanism open ("either proxies the FastAPI call or hands back the token for the client
to attach itself") while AC-10/FR-2's own literal call trace pins the retrofit's call signature —
`fetchProgramDetail(newId, { switchedFrom, accessToken })` — to a token **string** attached by the
existing fetch client, not a proxied response shape. Full-text detail and the resulting CORS
verification are in ADR-0008.

**Decision (as originally recorded — see D-10 for what actually shipped)**: `GET /api/session/token`
(new Route Handler) reads the cookie server-side, proactively refreshes if within the 60s skew,
and returns `{accessToken}` (200) or `{error:"session_expired"}` (401). `fetchProgramDetail`/
`fetchPrograms` are unmodified in their FastAPI-calling shape and reused verbatim by both call
paths — `page.tsx` sources `opts.accessToken` from `cookies()` directly, `ProgramDetailView`
sources it from this route first.

**Superseded**: reviewed and reversed — see D-10. FR-2's own title ("proxy through a Route
Handler"), the Solution sketch's "never directly," and TC-02's `expected_results` ("Route Handler
proxy") all point at full-proxy, and handing a raw token to client-side JS (even transiently, in a
variable) is exactly the XSS-exfiltration exposure the httpOnly cookie exists to avoid. Kept here,
unedited, as the record of the road not taken — see the `decide` skill's anti-pattern against
mutating a logged decision's rationale.

### D-03: Reactive-401 retry-once lives in one generic `tokenStore.callWithAuth()` helper · blast:feature · rev:mechanical · adr:—

**Context**: AC-7 requires "the frontend's server-side store" to own the reactive-401-then-retry
behavior, and TC-01 tests it as a `tokenStore`-level primitive independent of any specific FastAPI
call shape (its precondition mocks "a second mocked FastAPI call configured to return 401 once,
then 200 on retry" against the store, not against `fetchProgramDetail` directly). Duplicating this
retry logic once per caller (`page.tsx`, the `/api/session/token` route, any future caller) would
violate DRY and risk drift between copies.

**Decision**: `tokenStore.ts` exports `callWithAuth<T>(makeRequest: (accessToken: string) =>
Promise<T>, isUnauthorized: (result: T) => boolean): Promise<T>` — resolves a valid token
(proactive check), invokes `makeRequest`, and on `isUnauthorized(result)` calls `ensureTokenValid()`
reactively (sharing FR-1's single-flight guard with the proactive path) and retries `makeRequest`
exactly once with the refreshed token. `isUnauthorized` is caller-supplied so this one helper
composes with any result shape — a raw `Response.status === 401` in a test double, or
`fetchProgramDetail`'s own `status === "unauthorized"` discriminated-union variant in production
call sites.

### D-04: Callback redirect targets — success lands at `/`, any exchange failure lands at `/login` · blast:feature · rev:mechanical · adr:—

**Context**: AC-3 says a successful callback "302s the browser onward to the originally requested
page," but Scope Out explicitly drops return-URL preservation ("the user lands at `/login`'s own
post-auth destination, not back at the specific page they were viewing"). No AC pins a fixed
success landing page, and none pins callback-exchange-failure behavior (`invalid_state`,
`missing_code`, or a 401 from FastAPI's `/auth/callback`) at all — FR-5 only covers a
`/auth/refresh` failure.

**Decision**: On a successful exchange, `/callback` redirects to `/` — the app's own root route,
already the only generic landing page (`apps/web/src/app/page.tsx`), avoiding an invented route.
On any exchange failure, `/callback` redirects to `/login` rather than rendering a dedicated error
page — same "never surface a raw error, route back through sign-in" shape FR-5 already establishes
for the refresh-failure case, applied here by extension since no AC forbids it and no AC specifies
an alternative.

### D-05: `X-Program-Switch-From` stays in FastAPI's CORS `allow_headers` — not dead configuration · blast:feature · rev:mechanical · adr:— · **SUPERSEDED by D-11**

**Context**: FR-2's flagged consequence asks the implementation plan to verify whether any caller
still performs a direct browser-to-FastAPI request after this retrofit, and to say plainly whether
PGD-01's CORS `allow_headers` entry becomes dead.

**Decision (as originally recorded — see D-11 for the corrected finding)**: Per D-02,
`ProgramDetailView`'s calls continue to target FastAPI's real origin directly from the browser
(`fetchProgramDetail`/`fetchPrograms` are unmodified fetch clients, not proxied) — the switcher's
client-side reload still sends `X-Program-Switch-From` cross-origin, so the header remains
genuinely required for CORS preflight to succeed. No `services/api` change is made or needed.

**Superseded**: this conclusion was true only because D-02 chose vending. Once D-10 reverses that
to full-proxy, the premise (the browser still calls FastAPI directly) no longer holds — see D-11
for the corrected finding.

### D-06: `services/api/.env.example`'s `OIDC_REDIRECT_URI` gets a real local-dev default value · blast:feature · rev:mechanical · adr:—

**Context**: AC-1/AC-12 require `OIDC_REDIRECT_URI` to be set to the frontend's callback route
rather than left blank (research Risk R-02: an unset value silently falls back to the API's own
callback, breaking the intended frontend-first flow with no error). The field already exists
(`config.py:55`, blank in `.env.example:30`) — AUTH-05's only backend footprint is this value plus
docs (Constraints).

**Decision**: `services/api/.env.example`'s `OIDC_REDIRECT_URI=` line becomes
`OIDC_REDIRECT_URI=http://localhost:3000/callback`, matching the story's own illustrative local
value (AC-1, Decision log) and `docker-compose.yml`'s `web` port mapping (`3000:3000`). The
surrounding comment block is updated to state plainly that leaving this blank now breaks the
frontend-first flow rather than merely "mismatching a registered URI behind a proxy" (its current,
now-stale framing). This is a template-file edit — not `.env` itself, outside the governance deny
set, matching `apps/web/.env.example`'s own precedent from PGD-01.

### D-07: `tokenStore`'s single-flight guard is a per-process module-level variable · blast:feature · rev:mechanical · adr:—

**Context**: FR-1's guard (`refreshPromise`) is a plain module-level variable in a Node.js Next.js
server process. In a single-process local/dev deployment (`pnpm dev`, `docker compose up web`)
this dedupes every concurrent refresh trigger. In a multi-instance/multi-worker production
deployment, each process holds its own `refreshPromise`, so the guard dedupes only within one
process — the same shape as FastAPI's own `OAuthStateStore` (D-13/D-14, `app/auth/state_store.py`),
which carries an identical documented multi-replica caveat.

**Decision**: Accepted as-is, no cross-process coordination (e.g. a shared cache) added — no NFR or
AC requires cross-process dedup, and the cookie itself (not the guard) is the single source of
truth for the actual token value, so a multi-process race produces at most one extra, harmless
`POST /auth/refresh` call per affected process, never an inconsistent stored token.

### D-08: `programDetailApi` splits into a server module and a client module — not a boolean-forked single function · blast:feature · rev:mechanical · adr:—

**Context**: Under full-proxy (D-10), one logical fetch client now needs two genuinely different
behaviors depending on who calls it: server-side callers (`page.tsx`) hit FastAPI's real origin
(`getApiBaseUrl()`) with a token read from `cookies()` and attached as `Authorization`; client-side
callers (`ProgramDetailView.tsx`) hit the frontend's own same-origin proxy path and attach no
token at all — the proxy does that server-side. `.claude/rules/reusability-baseline.md` forbids
exactly the obvious shortcut here ("Avoid feature flags or config switches that fork the call
graph; refactor to a shared seam instead") — an `opts.viaProxy: boolean` branch inside one function
would be precisely that: a config switch forking `fetchProgramDetail`'s internal call graph between
two unrelated fetch targets and auth models.

**Decision**: Two modules, same function names and same result type
(`ProgramDetailResult`/`ProgramSwitcherEntry`, both now defined once in
`apps/web/src/types/programDetail.ts` so neither module's copy can drift). `programDetailApi.ts`
(server) keeps its existing FastAPI-direct, `accessToken`-attaching shape — used only by `page.tsx`
and, internally, by the two new proxy Route Handlers. `programDetailApi.client.ts` (new) targets
`/api/proxy/programs` / `/api/proxy/program-detail/[id]` and takes no `accessToken` opt at all —
used only by `ProgramDetailView.tsx`. A caller selects the right module by *which file it imports*,
not by a runtime flag or environment check (`typeof window` detection was considered and rejected:
implicit, untestable in isolation, and it would let a Server Component accidentally import the
client-only module without a compile error). Each module keeps `opts` additive per D-08's PGD-01
precedent (`switchedFrom?` on both; `accessToken?` only on the server module, since the client
module never resolves or holds a token to attach).

### D-09: Two dedicated proxy Route Handlers, not one generic pass-through · blast:feature · rev:mechanical · adr:—

**Context**: The client-side call surface is exactly two shapes today — `GET /api/programs` and
`GET /api/overview/program-detail/{id}`. A single generic `apps/web/src/app/api/proxy/[...path]/route.ts`
that reconstructs the FastAPI URL from client-supplied trailing path segments would cover both (and
any future shape) in one file — less code, and DRY across whatever client-side calls come next.

**Decision**: Two dedicated Route Handlers (`api/proxy/programs/route.ts`,
`api/proxy/program-detail/[program_id]/route.ts`) instead. Each targets a fixed, compile-time
FastAPI path — the client never controls which FastAPI endpoint gets called, only (for the second
route) the `program_id` path parameter within one already-open-aggregate-authorized endpoint
(`rbac.program_visibility`, AUTH-03). A generic `[...path]` proxy is a categorically broader
surface: it becomes a client-steerable reverse proxy into FastAPI's entire route table, and staying
safe would need its own allow-list of forwardable paths/methods/headers — which is more code and
more review burden than the two fixed handlers it would replace, not less, once that allow-list is
accounted for. Explicitly less DRY (two small handlers instead of one), traded for a narrower,
more obviously-auditable surface. Revisit if a third distinct client-side call shape appears and
the duplication becomes the bigger cost.

### D-10: Full request-proxy, not token-vending — supersedes D-02 · blast:system · rev:medium · adr:ADR-0008

**Context**: Reviewed and reversed from D-02 (token-vending). Full text of the reversal — why
FR-2's title, the Solution sketch's "never directly," and TC-02's `expected_results` outweigh the
literal `opts.accessToken` call-signature evidence D-02 leaned on, and why the XSS/token-exposure
difference is the deciding factor rather than a tie-break among readings — is in
`docs/adr/0008-client-side-auth-route-handler-proxy.md` (rewritten in place; same ADR number, since
this reversal happens within the same planning pass before any downstream artifact consumed the
original choice — not a later architectural change against shipped code).

**Decision**: `GET /api/proxy/programs` and `GET /api/proxy/program-detail/[program_id]`
(`apps/web/src/app/api/proxy/...`) are full request-proxies: each resolves a valid token via
`tokenStore.getValidAccessToken()`, calls the server-side `programDetailApi.ts` functions wrapped
in `tokenStore.callWithAuth()` (reusing D-03's retry-once helper — now exercised by three call
sites: `page.tsx` plus these two routes), and returns the result to the browser as JSON. No route
anywhere in this story hands a raw access token to client-side JavaScript. `GET /api/session/token`
is removed from the plan entirely — see `tasks.json` for the retargeted tasks.

### D-11: `X-Program-Switch-From` becomes dead CORS configuration under D-10 — carried forward, not fixed here · blast:feature · rev:mechanical · adr:—

**Context**: D-10 means `ProgramDetailView`'s client-side calls now terminate at the frontend's own
origin (`/api/proxy/*`) — same-origin, so no CORS preflight is triggered by the browser at all
regardless of which headers are sent. The proxy routes forward `X-Program-Switch-From` to FastAPI
server-to-server, which is never subject to CORS (a browser-enforced mechanism) in the first place.
FR-2's flagged consequence anticipated exactly this outcome and pre-settled the response: *"if none
does, the CORS entry becomes dead configuration for a future story to clean up, not this one."*

**Decision**: No `services/api` change (hard constraint, unchanged). PGD-01's CORS `allow_headers`
entry for `X-Program-Switch-From` (`services/api/app/main.py:72-78`) is left exactly as shipped —
removing it would be scope creep this plan does not take. Recorded instead as a named
`pending_carry_forward` entry in `docs/features/AUTH-05/state.json`
(`cors-x-program-switch-from-dead-config`, owner: a future `services/api` cleanup story, none
scheduled yet) — matching PGD-01's own precedent for `persona-chip-omission`/
`back-to-board-route-placeholder`. Not added to PLAN.md §6's risk tables (it isn't a research-risk
item; it's a plan-time finding, same category as those two PGD-01 items).
