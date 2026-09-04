# ADR-0008: Client-side authenticated FastAPI calls go through a same-origin Route Handler proxy — FastAPI is never reached directly from the browser

- Status: Accepted
- Date: 2026-09-04
- Deciders: impl-planning-agent (AUTH-05 plan), Pratik Pawar (pratik.pawar@apexon.com)

## Context

AUTH-05 gives the frontend a server-side token store (an httpOnly `dashboard_session` cookie) and
must let every FastAPI call `apps/web` makes attach `Authorization: Bearer <access_token>` —
including `ProgramDetailView.tsx`'s two client-side calls (`fetchPrograms()` on mount,
`fetchProgramDetail()` on a program switch). A client component cannot read an httpOnly cookie
(Next.js 15, `cookies()` is server-only), so the token has to reach the client component through
some same-origin server-side seam.

`docs/features/AUTH-05/REQUIREMENTS.md` FR-2 states the mechanism as an open choice: the client
path "must resolve `opts.accessToken` through a same-origin Route Handler that reads the cookie
server-side and **either proxies the FastAPI call or hands back the token for the client to attach
itself**." Two designs were viable:

1. **Full request-proxy** — a Route Handler per FastAPI endpoint the client needs performs the
   actual FastAPI call server-to-server and returns FastAPI's response to the browser; the raw
   access token never leaves the Node process.
2. **Token-vending** — a single Route Handler hands back the current (proactively-refreshed)
   access token as a string; the browser continues to call FastAPI's real origin directly, with
   `fetchProgramDetail`/`fetchPrograms` attaching the token as an `Authorization` header
   themselves.

This ADR originally chose token-vending, anchored on FR-2's literal call trace
(`fetchProgramDetail(newId, { switchedFrom, accessToken })`) as more concrete evidence than the
PRD's higher-level prose. **That choice was reviewed and reversed.** Re-reading the full evidence
set, three sources converge on full-proxy and none of them is ambiguous the way FR-2's body prose
is:

- **FR-2's own title**: "Client-side calls **proxy through a Route Handler**".
- **The PRD's Solution sketch**: `ProgramDetailView` and any future client-side caller "reach
  FastAPI only through this Route Handler layer, **never directly**."
- **`docs/test-cases/AUTH-05.json` TC-02's `expected_results`** (the authoritative field — see
  note below): the header is "sourced via the **Route Handler proxy**, not a direct `cookies()`
  read."

More importantly, the token-vending design has a real security cost the first pass under-weighted:
handing the raw access token to client-side JavaScript, even briefly and only in a variable, is
precisely the threat an httpOnly cookie exists to close off. An XSS on the page can read a
JS-held token and exfiltrate it for replay anywhere, outliving the page. Under full-proxy, the
same XSS can at most make same-origin calls while the page is open — the token itself never
enters a JS-reachable scope. This is the deciding factor, not just a tie-break among ambiguous
prose readings.

**Note on `docs/test-cases/AUTH-05.json`** (gate-approved, tracker-pushed #207–#210, not edited by
this plan): its `expected_results` line agrees with full-proxy, as quoted above. One of its
`steps` lines still reads "resolve `opts.accessToken` through a mocked Route Handler" —
vending-flavored wording left over from an earlier draft. The `expected_results` field is the
authoritative assertion; the `steps` line is stale phrasing, not a second, conflicting spec. Flagged
for the implementer so nobody treats that one line as license to build vending instead.

## Decision

Full request-proxy. Two dedicated Route Handlers — `GET /api/proxy/programs` and
`GET /api/proxy/program-detail/[program_id]` — each read the `dashboard_session` cookie
server-side, resolve a valid access token via `tokenStore.getValidAccessToken()`, call the
existing server-side `programDetailApi.ts` functions (`fetchPrograms()` /
`fetchProgramDetail(id, {switchedFrom, accessToken})`, unchanged FastAPI-calling implementation,
reused by `page.tsx` too) wrapped in `tokenStore.callWithAuth()` for the reactive-401-retry-once
behavior (AC-7), and return the result to the browser as JSON. `ProgramDetailView.tsx` calls these
two same-origin routes through a new, token-free client module
(`apps/web/src/lib/programDetailApi.client.ts`) and never touches a token, a cookie, or
`tokenStore` in any form — see `DATA-DESIGN.md`/`DECISIONS.md` D-08 for the module-split seam this
implies, and D-09 for why two dedicated routes rather than one generic pass-through.

## Consequences

- Positive: the access/refresh token pair never leaves the Node server process under any
  code path this story adds — a materially stronger XSS/token-exfiltration posture than
  token-vending, and the one every future frontend story that calls a protected FastAPI route
  from a client component now inherits (call the proxy, get no token back, done). Matches FR-2's
  title, the Solution sketch's "never directly," and TC-02's `expected_results` exactly — no
  reading-a-flagged-consequence-against-itself tension like the vending choice had.
- Negative: more Route Handler code than a single token-vending endpoint — one dedicated proxy per
  FastAPI shape the client needs, versus one generic token endpoint reusable by any future call.
  Confirms FR-2's own flagged consequence the other way: PGD-01's CORS `allow_headers` entry for
  `X-Program-Switch-From` (`services/api/app/main.py:72-78`) is now genuinely dead — no browser
  request reaches FastAPI's origin directly anywhere in this story's code, so that header never
  crosses a real CORS boundary again. Recorded as a carry-forward for a future story to clean up,
  not fixed here (DECISIONS.md D-11; `services/api` stays untouched by this plan).
- Reversible? Medium — same cost profile as the rejected alternative, just in the other direction:
  switching to token-vending later means collapsing the two dedicated proxy routes into one token
  endpoint and rewiring `programDetailApi.client.ts` (and every future frontend story that has, by
  then, built its own dedicated proxy route following this ADR) to attach the header itself
  instead. Not a data migration, but a coordinated rewrite.
