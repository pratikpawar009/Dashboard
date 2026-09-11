# OVW-05 — Data Design

State & data management for the CIO shell regions + branded sign-in page. Each concern below is specified or marked `N/A — <reason>`.

## 1. Data model

`N/A — no persistent entity.` The only new "shape" is an ephemeral, per-request client-side composition (`SignedInUser`), derived from two existing API responses (`overview-summary-api`, `session-identity-api`); nothing is written to a store.

## 2. Migrations

`N/A — no schema, no Alembic revision, no store touched.` This story is frontend-only.

## 3. Ownership & tenancy

`N/A — no new owned resource.` `/overview` remains `org_access`-gated (AUTH-03), unchanged by this story. `login/page.tsx`'s `readSession()` call reads the existing `dashboard_session` cookie (AUTH-05) — a read of an existing per-browser session, not a new ownership boundary.

## 4. Data classification & retention

`name` (PII) already flows through `GET /api/me` (AUTH-07-owned, unchanged shape, `extra="forbid"`). This story never writes `name`/`persona` to any store or log — NFR-Observability confirms no new logging event, and `composeSignedInUser()` (`apps/web/src/lib/composeSignedInUser.ts`) is a pure, non-logging function operating on already-in-memory data. No new retention/deletion policy is introduced.

## 5. Consistency & concurrency

`overview/page.tsx` issues `GET /api/overview/summary` and `GET /api/me` **concurrently** via `Promise.all` (DECISIONS.md D-02), a change from today's single-call shape. Both ride `tokenStore`'s existing single-flight refresh guard (FR-1, module-level `refreshPromise`) for the access-token proactive-refresh race, so no torn-token or duplicate-refresh risk is introduced by the concurrency. No transactions and no idempotency keys are needed — both calls are read-only GETs with no side effects.

## 6. Caching

No new cache. `session-identity-api`'s `resolve()` stays process-cached 300s TTL, unowned by this story (AUTH-02/AUTH-07). This story adds no frontend cache layer of its own — every `/overview` render re-issues both GETs; `session-identity-api`'s TTL is the only thing that absorbs repeat-load latency inside its window.

## 7. Ephemeral / session state

`dashboard_session` httpOnly cookie (AUTH-05, unchanged) is **read** by the new `login/page.tsx` via the existing `readSession()` helper (`apps/web/src/lib/tokenStore.ts`) — the same helper `GET /logout` already calls — to implement the already-authenticated pass-through (AC-18). No new cookie, no new session field, no new client-side store is introduced.

## 8. Query-path & access-path performance

Two concurrent GETs per `/overview` render (up from one today) share the page's existing ≤3s render budget (NFR-001) — no separate budget is set for the added call (story NFR, Decision log). Neither call is a list endpoint, so no pagination concern applies. `session-identity-api`'s existing 300s process cache absorbs repeat-load latency for sessions re-rendering inside that window.

## 9. Contract (API / interface)

Registered, cross-story contracts (authored in the shared registry, bookmarked here — not duplicated):

- `Contract: persona-shell → docs/requirements/api.md#persona-shell` — co-produced with SHP-01; this story adds the `pageTitle` prop and the sign-out control's shape as new keys in that shared file (see PLAN.md § 5, task touching `docs/requirements/api.md`).
- `Contract: session-identity-api → docs/requirements/api.md#session-identity-api` — AUTH-07's frozen `{name, persona}` shape, consumed unchanged; no request/response modification.

Feature-internal (no other story consumes these — described inline):

- `fetchMe(opts?: { accessToken?: string }) @ apps/web/src/lib/meApi.ts` → `Promise<MeResult>`, where `MeResult = {status:"ok", data: MeData} | {status:"forbidden"} | {status:"unauthorized"} | {status:"error"}` and `MeData = {name: string | null; persona: string}` (`apps/web/src/types/me.ts`). Consumer of FastAPI's `GET /api/me`; mirrors `overviewApi.ts::fetchOverviewSummary`'s status-mapping (DECISIONS.md D-01).
- `composeSignedInUser(me: MeData) @ apps/web/src/lib/composeSignedInUser.ts` → `SignedInUser | undefined`. Pure function, no I/O: `name === null` → `undefined`; otherwise `{name, jobTitle: formatPersonaTag(me.persona).jobTitle}`, catching `PersonaTagError` back to `undefined` when `persona` is unresolvable (DECISIONS.md D-03).

## 10. Async & messaging

`N/A — purely synchronous request/response.` No new event, queue, or scheduled job is introduced.
