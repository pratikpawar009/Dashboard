# Feasibility Assessment: OVW-05

**Story**: OVW-05 — CIO shell regions: signed-in identity block + org page-title header  
**Status**: Research  
**Assessment Date**: 2026-09-11  
**Verdict**: GO-WITH-CONDITIONS  

## Upstream Dependencies

- **AUTH-07** (session-identity-api): `GET /api/me` shipped and merged (commit defe50b, PR #284, phase=implemented). Endpoint returns sealed `{name: str | null, persona: str}` response with `extra="forbid"`, frozen contract matches story assumption. No stale prose risk — dependency is production-ready.
- **SHP-01** (persona-shell): `PersonaDashboardShell.tsx`, `formatPersonaTag.ts`, `apps/web/src/types/persona.ts` all shipped and reviewed. Co-producer contract (OVW-05 extends, SHP-01 does not change) is stable.

Per phase-preconditions: both upstreams have `research_verdict: GO-WITH-CONDITIONS`, phases `review` / `security-reviewed` — gate passes.

## Exploration Log

### Frontend Persona System

- **Files**: `apps/web/src/types/persona.ts:29-34`, `apps/web/src/lib/formatPersonaTag.ts:42-67`
- **What**: Four hardcoded personas (architect, developer, product-manager, engineering-manager); no CIO entry. `VALID_PERSONAS` array is 4-entry const; `PERSONA_DISPLAY` map has matching 4 entries.
- **Surprises**: Docstring at `formatPersonaTag.ts:22-23` explicitly asserts that `cio` would be "an invariant violation, not a fifth persona to render" — inverse of story's intent. This docstring must be rewritten as part of AC-4.
- **Open**: None — CIO admission to the persona set is straightforward const-array extension.

### PersonaDashboardShell Component

- **Files**: `apps/web/src/components/PersonaDashboardShell.tsx:63-120` (partial read)
- **What**: Brand bar (logo, product name, tagline) + optional identity block (signed-in user name/job-title + avatar). Two props: `signedInUser?: {name, jobTitle}` and `persona?: string`. Conditional rendering based on `isLoading = persona === undefined`.
- **Surprises**: Identity block already renders job title (line 96: `{signedInUser.jobTitle}`) but `SignedInUser` interface at `types/persona.ts:15-18` has no `jobTitle` field — only `name: string`. This is a type mismatch; AC-3 resolves it by adding the field.
- **Open**: Org-header region (pageTitle prop, second header variant) is not implemented. Sign-out control is not implemented. Both require code additions; no blockers found.

### AdoptionOverview Component

- **Files**: `apps/web/src/components/AdoptionOverview.tsx:33-51`
- **What**: Org-wide summary page. Renders `PersonaDashboardShell` with all persona/identity props omitted (lines 35: `<PersonaDashboardShell>` with no props). Component receives `result: OverviewSummaryResult` and renders summary cards + adoption indicator.
- **Surprises**: Shell is intentionally rendered with `isLoading=true` (persona undefined) — brand bar only, no identity or header. Story AC-5 requires adding the `GET /api/me` call and passing resolved identity to the shell.
- **Open**: Fetch location — inline in `/overview/page.tsx` or extracted to `meApi.ts`. Story has no opinion; either pattern is acceptable (Assumption, no source, Decision log).

### Mockup Design Verification

- **File**: Decoded `docs/design/mockups/CIO Portfolio Dashboard.html`
- **What**: Brand bar shows signed-in user (name "Elena Vasquez", job title "Chief Information Officer", 34×34 avatar with #0f1a2e background). Org header shows page title "Adoption Overview" + "CIO / CXO" pill + subtitle "Organization-wide AI-in-SDLC adoption, spend & impact".
- **Surprises**: No sign-in screen, no sign-out affordance in any of the six mockups. Both ACs 12-19 are **deliberate, recorded deviations** per story Decision log.
- **Open**: None — design contract is explicit.

### Login/Logout Infrastructure

- **Files**: `apps/web/src/app/login/route.ts` (OAuth relay), `apps/web/src/app/logout/route.ts` (logout relay), no `/login/page.tsx` exists
- **What**: `route.ts` files handle OAuth handshake with FastAPI. No branded sign-in page UI exists. `logout` route is ready for linking.
- **Surprises**: **Routing conflict risk** — `/login` directory already has `route.ts` (Route Handler). AC-16 requires a branded sign-in page. If a `page.tsx` is added to the same directory, Next.js routing precedence (route.ts > page.tsx in same segment) makes the page unreachable by default.
- **Open**: None — **RESOLVED 2026-09-11** (user decision). The branded page takes `/login` (`apps/web/src/app/login/page.tsx`); the relay handler moves down one segment to `apps/web/src/app/login/start/route.ts` (`GET /login/start`), body unchanged. A parent `page.tsx` and a child `route.ts` coexist without conflict. Two corrections to the scan that produced this item: (i) a `+api` segment is **not** a Next.js App Router feature (it is SolidStart/Expo Router) — that option was never available; (ii) `login/route.ts:12-13`'s docstring claims `OIDC_REDIRECT_URI` "must exact-match this path", which is **false** — `AUTH-05-FR-3` ties that constraint to `/callback`, and `OIDC_REDIRECT_URI` is `http://localhost:3000/callback`. No registered Keycloak URI pins the relay to `/login`, so it is free to move.

### API Dependency Surface

- **Search**: `GET /api/me` fetch location in frontend code
- **What**: `apps/web/src/app/overview/page.tsx` currently calls `fetchOverviewSummary()` via `tokenStore.callWithAuth()`. `GET /api/me` must follow the same pattern.
- **Surprises**: None — pattern is established and reusable.
- **Open**: Whether to inline fetch or extract `meApi.ts`. No blocking decision; assumption, Decision log entry.

## Pattern Map

### Existing Code to Extend

- **`apps/web/src/types/persona.ts`**: Add `"cio"` to `VALID_PERSONAS` array (4→5 entries). Add `jobTitle: string` field to `SignedInUser` interface (AC-3).
- **`apps/web/src/lib/formatPersonaTag.ts`**: Extend `PERSONA_DISPLAY` with `cio` entry (colors/tag/subtitle sourced from decoded mockup, AC-2). Add `jobTitle: string` field to all 5 persona entries (AC-3). Rewrite docstrings to acknowledge `cio` as valid persona (AC-4).
- **`apps/web/src/components/PersonaDashboardShell.tsx`**: Add optional `pageTitle?: string` prop. Add org-header variant (render when `pageTitle && persona && !program`, AC-8). Add sign-out affordance to identity block (AC-12/13).
- **`apps/web/src/components/AdoptionOverview.tsx`**: Wrap `GET /api/me` call via `callWithAuth()`. Compose `signedInUser` from response (AC-5/7). Pass `persona`, `signedInUser`, `pageTitle="Adoption Overview"` to shell (AC-9).
- **`apps/web/src/app/overview/page.tsx`**: Add `GET /api/me` fetch (inline or via `meApi.ts`).

### Existing Patterns to Follow

- **Persona validation**: `VALID_PERSONAS` membership check; throw on miss (never default/invent).
- **Server Component data flow**: `callWithAuth()` for fetch, `SessionExpiredError` → redirect, other results → pass to component for rendering.
- **Identity styling**: Reuse `.identity`, `.name`, `.jobTitle`, `.avatar` classes from `PersonaDashboardShell.module.css`.
- **Route linking**: Sign-out → `/logout` (no new route), sign-in page → `/login` route handler.

### New Files to Create

- **`apps/web/src/app/login/page.tsx`** (AC-16): Branded sign-in page with brand bar + SSO button. Server Component. Check for existing session → continue to destination if already signed in (AC-18).
- **`apps/web/src/lib/meApi.ts`** (optional AC-5): Encapsulate `GET /api/me` fetch if reused; inline in `/overview/page.tsx` is acceptable for now.

### Shared Code at Risk

- **`apps/web/src/types/persona.ts`** — `SignedInUser` interface: Adding `jobTitle` field is a required string; TypeScript will catch construction-site errors. No breaking change (field is consumed only by `PersonaDashboardShell`, which will read it).
- **`apps/web/src/lib/formatPersonaTag.ts`** — `PERSONA_DISPLAY` map: Must maintain byte-exact colors from decoded mockup. Mitigation: lock values in comments with source citation.
- **`apps/web/src/components/PersonaDashboardShell.tsx`** — header variants: Org-header and program-header are mutually exclusive (`program === undefined` for org). Test fixture confirms conditional logic; no collision risk.
- **`apps/web/src/app/overview/page.tsx`** — fetch pattern: Adding `GET /api/me` adds latency but shares existing ≤3s render budget (OVW-01 NFR-001). No separate budget needed.

## Risk Register

| # | Dimension | Severity | Description | Mitigation |
|---|-----------|----------|-------------|-----------|
| 1 | Dependency | HIGH | Story prose describes AUTH-07's `GET /api/me` as "unshipped"; endpoint is actually live (merged, phase=implemented). Stale documentation could mislead planning. | Update story Dependencies section to reflect AUTH-07's actual merged state. Verify endpoint shape matches frozen contract before implementation. |
| 2 | Domain | HIGH | Job title field must be composed frontend-side from `PERSONA_DISPLAY[persona].jobTitle` per spec (AC-3). System carries no seniority/tenure data. Returning `jobTitle` from backend violates architecture. | Never expect `jobTitle` from `GET /api/me` response. Derive locally only. Add test assertion in `AdoptionOverview` test confirming composition, no backend pass-through. |
| 3 | Integration | MED | Two sequential fetches on `/overview` page render. Latency stacking risk even with 300s backend cache. Initial load must complete before page renders. | No new timeout/retry logic (shares `callWithAuth` pattern). Page's existing ≤3s budget (OVW-01 NFR-001) covers both. Timing verified in test fixture. |
| 4 | Compatibility | MED | `SignedInUser` interface gains `jobTitle` field. Existing inline object construction could silently miss field. TypeScript error at call sites. | Scan for `{...name...}` patterns. Field is required string (TypeScript catch). Update test fixtures to include both fields. |
| 5 | Compatibility | LOW (was MED blocker) — **RESOLVED 2026-09-11** | `/login` cannot hold both `page.tsx` and `route.ts`. Settled by user decision: branded page at `apps/web/src/app/login/page.tsx`; relay moves to `apps/web/src/app/login/start/route.ts`. Driven by AC-16 (which names the `/login` surface) and by `FRONTEND_LOGIN_URL=http://localhost:3000/login` being Keycloak's registered `post_logout_redirect_uri` — while `/login` auto-relays, AUTH-07 logout bounces the user straight back into the IdP and no dashboard-owned screen is ever shown. | Move the file, keep its body byte-identical; point the page's SSO action at `/login/start`. Residual LOW work carried into PLAN: (a) all 7 shipped `redirect("/login")` call sites stay correct and need no edit — assert this in test; (b) `login/route.ts:12-13`'s `OIDC_REDIRECT_URI` docstring is factually wrong and must be corrected in the moved file; (c) AC-18 requires `login/page.tsx` to read `dashboard_session` server-side and redirect onward when a valid session exists, preserving AUTH-05's silent pass-through for an authenticated user. |
| 6 | Domain | MED | Sign-out affordance (AC-12/13) is mockup deviation. Must be keyboard-accessible, aria-labeled, contrast-compliant (WCAG AA, NFR-a11y per OVW-01). | Use semantic `<button>` (not `<div>`). Include `aria-label="Sign out"`. Tab → Focus visible. Color contrast ≥4.5:1. Test covers all ACs 12–14. |
| 7 | Performance | LOW | Two server fetches on `/overview`. If `/api/me` fails, whole page fails (no graceful identity-only degradation). | `GET /api/me` failure (401/403) handled by `callWithAuth` same as `overview-summary`: redirect on SessionExpiredError, pass non-ok to component. Component renders error panel per D-07. Pattern is consistent. |
| 8 | Dependency | LOW | Frontend `VALID_PERSONAS` and backend `persona_resolver` must stay in sync. Drift risk if new persona added to one system only. | Document sync dependency in `PERSONA_DISPLAY` header comment. Recommend Change Review rule: new persona MUST update both frontend and backend simultaneously. |

## Scoring

| Dimension | Weight | Score | Weighted |
|-----------|--------|-------|----------|
| Integration | 25% | 75 | 18.75 |
| Compatibility | 20% | 80 | 16.0 |
| Domain | 20% | 70 | 14.0 |
| Performance | 15% | 80 | 12.0 |
| Dependency | 20% | 80 | 16.0 |
| **Total** | — | — | **76.75 → 77/100** |

**Total: 77/100 → GO-WITH-CONDITIONS**

_Rescored 2026-09-11 after the routing clarification was resolved: Compatibility 65 → 80 (the blocker retired; risk #4 `SignedInUser`/`jobTitle` remains MED). No other dimension re-scored._

**Conditions for GO** (0 open clarifications — the routing blocker is retired; `/arh-plan-requirements` is unblocked). PLAN.md must explicitly address:

1. **Risk #2 (HIGH, Domain)** — `jobTitle` is composed frontend-side from `PERSONA_DISPLAY[persona].jobTitle` and is never read from `GET /api/me`. Carry a test asserting no backend `jobTitle` passes through.
2. **Risk #5 residuals (Compatibility)** — the three carried items in the risk register: unchanged `/login` call sites, the wrong `OIDC_REDIRECT_URI` docstring in the moved file, and AC-18's server-side session check in `login/page.tsx`.
3. **Risk #8 (LOW, Dependency)** — record the frontend `VALID_PERSONAS` ↔ backend `persona_resolver` sync obligation.

## Synthesis

OVW-05 is **ready for planning; 0 open clarifications**. The story extends a stable persona-shell component (SHP-01, shipped) and an already-live identity endpoint (AUTH-07, merged in `defe50b` / PR #284). The work is well-scoped: admit `cio` as a fifth persona frontend-side, integrate an existing `GET /api/me` call, compose identity data, and render two new UI regions (org header + sign-out control) plus the branded sign-in page. Design is explicit; every acceptance criterion traces to the decoded mockup or a recorded deviation. The one blocker — a Next.js routing collision at `/login` — was resolved on 2026-09-11: the branded page takes `/login`, the relay moves to `/login/start`. That choice is forced by more than tidiness: `FRONTEND_LOGIN_URL` makes `/login` Keycloak's post-logout landing site, so leaving it an auto-relay would have left AUTH-07's logout bouncing users straight back into the IdP with no dashboard-owned screen — precisely what AC-16 exists to prevent. Residual risk is low: no new stack patterns, no external dependencies beyond already-shipped services, and a clear architectural boundary (persona display composed frontend-side, no seniority data from the backend). The remaining HIGH item is a discipline constraint, not an unknown — `jobTitle` must never arrive from the API. Latency and compatibility risks are covered by existing patterns and the page's ≤3s budget.

## Clarifications

## Resolved clarifications

- _Resolved 2026-09-11 — was the only open item; `## Clarifications` above is intentionally empty so the phase gate reads clean._ **Where should the branded sign-in page live, given `/login/route.ts` already exists?** — **user decision:** branded page at `apps/web/src/app/login/page.tsx`; relay handler moves to `apps/web/src/app/login/start/route.ts`. Rationale and residual work in risk #5 and the Exploration Log. The originally-offered option (a) (`+api` segment) was invalid — `+api` is not a Next.js App Router feature.

---

**Research state write**: `research: "complete"`, `research_verdict: "GO-WITH-CONDITIONS"`, `phase: "research"`
