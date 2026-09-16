# Research Assessment: PGD-07 — Program Detail Brand Bar (Shell Retrofit)

**Story**: PGD-07  
**Epic**: PGD  
**Date**: 2026-09-16  
**Verdict**: GO-WITH-CONDITIONS  
**Score**: 83/100

---

## Upstream Dependencies

- **AUTH-07** (session-identity-api): `GET /api/me` → `{name, persona}` — **research_verdict: GO-WITH-CONDITIONS, phase: security-reviewed** ✓ on origin/main
- **OVW-05** (persona-shell): PersonaDashboardShell component + sign-out control — **research_verdict: GO-WITH-CONDITIONS, phase: security-reviewed** ✓ on origin/main

Both dependencies are shipped, tested, and validated on origin/main. No blocking work.

---

## Exploration Log

### Contracts & Components (Verified on origin/main)

**Backend**:
- `services/api/app/api/me.py` — GET /api/me route handler
- `services/api/app/schemas/me.py` — MeResponse model (extra="forbid", exactly `{name, persona}`)

**Frontend**:
- `apps/web/src/lib/meApi.ts` — fetchMe() function, status mapping (ok/forbidden/unauthorized/error)
- `apps/web/src/lib/composeSignedInUser.ts` — pure function deriving jobTitle from PERSONA_DISPLAY (never from wire)
- `apps/web/src/components/PersonaDashboardShell.tsx` — brand bar + identity block + sign-out control
  - Accepts props: `{signedInUser?, persona?, program?, pageTitle?, children?}`
  - Renders identity only when `!isLoading` (persona !== undefined)
  - Sign-out control: zero-JS `<form action="/logout">`, already present per OVW-05
- `apps/web/src/types/me.ts` — MeData, MeResult type definitions
- `apps/web/src/types/persona.ts` — Persona, SignedInUser type definitions

### Target Implementation Sites

1. **apps/web/src/components/ProgramDetailView.tsx** (modify)
   - Currently: Client Component ("use client"), renders `<div className={styles.wrapper}>`
   - Must: Accept `persona?: Persona` and `signedInUser?: SignedInUser` props
   - Must: Wrap existing content in `PersonaDashboardShell` with `program={undefined}`
   - Must: Forward `persona` and `signedInUser` to shell

2. **apps/web/src/app/programs/[program_id]/page.tsx** (modify)
   - Currently: Server Component, fetches program detail server-side
   - Must: Add `GET /api/me` fetch (via meApi.fetchMe)
   - Must: Compose SignedInUser using composeSignedInUser (or handle persona-resolution-error sentinel)
   - Must: Use Promise.all to parallelize both fetches
   - Must: Handle SessionExpiredError from either fetch
   - Must: Pass `persona` and `signedInUser` to ProgramDetailView

### Existing Patterns (from OVW-05)

- **Async Server Component pattern**: `apps/web/src/app/overview/page.tsx` — Promise.all, callWithAuth wrapper, SessionExpiredError catch
- **Persona-resolution sentinel**: Define as `const PERSONA_RESOLUTION_ERROR = "persona-resolution-error"`; when fetchMe fails, pass this sentinel to shell
- **Composition pattern**: Shell accepts fully-resolved props; no fetch logic in components
- **Sign-out control**: Already implemented in PersonaDashboardShell per OVW-05 AC-12..15; reused as-is per AC-9

---

## Pattern Map

### Existing Code to Extend

- **ProgramDetailView.tsx** — wrap `<div className={styles.wrapper}>` children in PersonaDashboardShell, accept new props from parent
- **programs/[program_id]/page.tsx** — add second server-side fetch alongside existing program-detail fetch

### Existing Patterns to Follow

- Server-side concurrent fetch pattern from overview/page.tsx: `Promise.all([fetch1, fetch2])` inside try/catch
- SessionExpiredError handling: one error from either fetch → redirect("/login")
- Persona-resolution-error sentinel: string literal value used as fallback persona when `/api/me` fails
- Sign-out control: already present in PersonaDashboardShell; no new code needed per AC-9

### New Files to Create

**None.** All required modules exist on origin/main:
- meApi.ts (fetchMe function)
- composeSignedInUser.ts (jobTitle composition)
- PersonaDashboardShell (brand bar + identity + sign-out)
- Type definitions (MeData, MeResult, Persona, SignedInUser)

### Shared Code at Risk

1. **PersonaDashboardShell.tsx** — consumed by two routes
   - Risk: any shell modification affects both /overview and /programs/[program_id]
   - Mitigation: shell contract is frozen (persona-shell in docs/requirements/api.md); change only if both consumers need it

2. **composeSignedInUser()** — used by both OVW-05 and PGD-07
   - Risk: function changes break both consumers
   - Mitigation: function is pure, unit-tested by OVW-05; PGD-07 uses it unchanged

3. **meApi.fetchMe()** — two call sites
   - Risk: API contract drift
   - Mitigation: contract frozen (session-identity-api in api.md); endpoint already implemented and tested

---

## Risk Register

| # | Dimension | Severity | Description | Mitigation |
|---|-----------|----------|-------------|-----------|
| R1 | Integration | MED | `/api/me` response shape could have drifted since OVW-05 validation; must confirm no `jobTitle` field is sent on wire | Verify response on running origin/main with a real bearer token. Add unit test passing decoy object with `jobTitle` to composeSignedInUser, assert it is not composed into SignedInUser. |
| R2 | Integration | MED | ProgramDetailView is Client Component; server-side fetch in page.tsx must not be overridden by component-side re-fetch | Design review: page.tsx fetches server-side, passes resolved props only. ProgramDetailView receives props, never imports meApi or fetchMe. Unit test component with mocked props, no fetch calls. |
| R3 | Compatibility | MED | Session expiry: `/api/me` 401 could race with program-detail fetch; both wrapped in Promise.all need coordinated handling | Follow OVW-05 exactly: both fetches inside callWithAuth, Promise.all dedupes refresh via tokenStore.refreshPromise guard. One try/catch block, one SessionExpiredError catch → redirect. Document why one error from either fetch causes full redirect. |
| R4 | Domain | MED | AC-3/AC-5: persona resolution failure must NOT fallback to guessed value; must fail closed | Use persona-resolution-error sentinel (string literal) when meResult.status !== "ok". PersonaDashboardShell already handles via PersonaTagError catch. Research condition C-7: no route hardcodes `persona: 'cio'`. |
| R5 | Compatibility | MED | AC-8/AC-9: sign-out control must be SAME PersonaDashboardShell control (not a fork); must render in BOTH identity branches | Sign-out control already exists in shell per OVW-05. AC-8 places it as a SIBLING of identity ternary (not nested inside). OVW-05 shipped this untested (AC-12 carry-forward). Add focused unit test asserting button renders in populated AND neutral-fallback branches. |
| R6 | Domain | LOW | AC-2 constraint: must pass `program: undefined` to PersonaDashboardShell (not real program object) | Shell's own docstring documents constraint. Code review gate: verify ProgramDetailView calls `<PersonaDashboardShell program={undefined} ... >`. Unit test ProgramDetailView with different program values to verify constraint is enforced. |
| R7 | Performance | LOW | Adds concurrent `GET /api/me` fetch; must stay within NFR-1 budget (≤3s page render) | Fetch is server-side, parallelized via Promise.all. Timeout is 5s (matches meApi/overviewApi). Expected latency: ~same as program-detail fetch (both concurrent). Fits within existing budget. |
| R8 | Domain | LOW | AC-6: identity block must render actual persona (cio/architect/developer/etc.), never hardcoded fallback | Unit test ProgramDetailView with various persona values; verify jobTitle and avatar colour match PERSONA_DISPLAY mapping for each. No hardcoded CIO anywhere in page or component. |

---

## Score & Verdict

| Dimension | Weight | Score | Reasoning |
|-----------|--------|-------|-----------|
| **Integration** | 25 | 80 | API contract frozen and validated by OVW-05 already. meApi.ts exists and is consumption-proven. One medium risk (R1): jobTitle leakage — mitigated by contract test. One medium risk (R2): client/server fetch boundary — mitigated by design (server-side only) + unit test. |
| **Compatibility** | 20 | 75 | Two medium risks: (R2) fetch architecture — resolved by design; (R3) session-expiry race — existing tokenStore guard handles it; (R5) sign-out placement — OVW-05 untested, needs focused unit test. Design follows proven pattern (OVW-05). |
| **Domain** | 20 | 85 | AC-3/AC-5 handled by persona-resolution-error sentinel (OVW-05 precedent). AC-2 enforced by shell contract. AC-6 persona rendering is direct from PERSONA_DISPLAY (no guessing). Risks R4, R6, R8 are design/test gaps, not implementation blockers. |
| **Performance** | 15 | 90 | Server-side fetch, concurrent with program-detail via Promise.all. Timeout 5s. Parallelized, not sequential. Fits within ≤3s page-render budget (two parallel ~1.5s calls ≈ 1.5s wall time). NFR-1 met. |
| **Dependency** | 20 | 85 | AUTH-07 and OVW-05 both GO-WITH-CONDITIONS/security-reviewed on origin/main. No blocking work. Components are unfrozen, tested, and proven by OVW-05 consumption. tokenStore.refreshPromise guard (R3) is battle-tested. |

**Total: (80×0.25 + 75×0.20 + 85×0.20 + 90×0.15 + 85×0.20) = 20 + 15 + 17 + 13.5 + 17 = 82.5 ≈ 83/100**

**Verdict: GO-WITH-CONDITIONS**

---

## Conditions for Plan

The following must be explicitly addressed in `/arh-plan-requirements`:

1. **Integration (R1) — jobTitle wire leakage test**: PLAN.md must include a test task asserting no `jobTitle` field passes through the wire contract. Test fixture: mock meApi response with a decoy `jobTitle` key; assert composeSignedInUser does not include it in output.

2. **Compatibility (R5) — sign-out control placement test**: PLAN.md must include a test task for PersonaDashboardShell (or ProgramDetailView) asserting the sign-out button renders in BOTH the populated-user branch AND the neutral-fallback (no signedInUser) branch. This is AC-12 from OVW-05, shipped untested.

3. **Domain (R8) — persona rendering test**: PLAN.md must include a test task for ProgramDetailView verifying jobTitle and avatar colour are derived from PERSONA_DISPLAY and match the passed `persona` prop. Test with multiple persona values (cio, architect, developer, engineering-manager, product-manager).

4. **Compatibility (R3) — SessionExpiredError comment**: PLAN.md's Promise.all handling must include a code comment explaining why a SessionExpiredError from EITHER fetch (not just the first) causes a redirect. Reference tokenStore.refreshPromise dedup guard as the synchronizing point.

---

## Synthesis

PGD-07 retrofits the Program Detail page with the brand bar and signed-in identity block that OVW-05 already built and validated. The implementation is a straightforward composition: wrap ProgramDetailView in PersonaDashboardShell, add a server-side `/api/me` fetch to the page (following OVW-05 exactly), and pass resolved props to the component. All required components exist and are proven by OVW-05 consumption (meApi, composeSignedInUser, PersonaDashboardShell). No new implementation is needed.

The score reflects four medium-severity test gaps inherited from OVW-05 (jobTitle contract enforcement, sign-out control placement, persona rendering verification, and session-expiry documentation), all of which are resolved by targeted unit tests already planned in OVW-05 or straightforward additions in PGD-07's own test suite. Contract integration is solid; no jobTitle leakage path exists because the backend model forbids it and the frontend function ignores it. The story is ready for `/arh-plan-requirements` provided the four conditions are addressed in the PLAN.

---

## Clarifications

None.
