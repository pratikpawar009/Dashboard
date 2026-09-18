# Story: AUTH-08 — Persona-based post-login routing

**Epic**: AUTH
**Status**: Validated
**Priority**: P1
**Owner**: —
**Updated**: 2026-09-18
**Tracker**: pratikpawar009/Dashboard#483 (https://github.com/pratikpawar009/Dashboard/issues/483)

## User story

As any signed-in user, I want to land on the dashboard that matches my persona,
so that I see my own view instead of a CIO-only page that refuses me.

## Context

Today every authenticated user is routed to the same place. `/callback` redirects to `/`
(`apps/web/src/app/callback/route.ts:65`), and `/` unconditionally redirects to
`ADOPTION_OVERVIEW_ROUTE` (`apps/web/src/app/page.tsx`, `apps/web/src/lib/routes.ts`) — a
single hardcoded constant with no persona branching anywhere in the chain.

`/overview` is CIO-only: both of its regions call `org_access`, which passes only for
`persona == "cio"` (`services/api/app/core/rbac.py:85`). So an Architect, EM, Developer or
PM who signs in lands on a page that renders two stacked "You don't have access to this
view." panels — one per region — with no path to anything they can use. Observed live on
2026-09-18 with a real Keycloak SSO session.

This is a routing gap, not a missing-dashboard problem. `ARC-01`, `EMD-01`, `DEV-01` and
`PMD-01` build the four persona dashboards, but none of them owns the decision of where a
given persona lands, and none changes the hardcoded redirect. The gap is therefore real
today and will still be real the day those four ship.

`GET /api/me` (AUTH-07) already returns the resolved `persona`, so the seam this story needs
exists and is shipped. No new backend endpoint is required.

## Acceptance criteria

1. Given a user completes sign-in, when `/callback` hands off, then the destination is
   resolved from the session's persona (via the shipped `GET /api/me`) rather than a single
   hardcoded route shared by every persona.
2. Given a signed-in `cio`, when post-login routing resolves, then they land on the Adoption
   Overview (`/overview`) exactly as they do today — no behavioural change for the persona
   whose surface already exists.
3. Given a signed-in persona whose dashboard has shipped, when post-login routing resolves,
   then they land on that persona's own dashboard route.
4. Given a signed-in persona whose dashboard has NOT shipped yet, when post-login routing
   resolves, then they land on that persona's own dedicated route, which renders a
   purpose-built "your dashboard isn't available yet" state naming their persona — never the
   CIO page's access-denied panels, and never a 404. The route exists from this story onward;
   only what it renders changes when that persona's dashboard story ships.
5. Given a user navigates directly to a route their persona may not access, when the page
   loads, then they are routed to their own landing surface rather than shown a bare denial.
6. Given the Adoption Overview renders for a non-CIO persona by any path, when its regions
   fail authorization, then at most ONE access-denied message is shown for the page, not one
   per region (today two identical panels stack).
7. Given persona resolution fails, returns no persona, or returns a persona outside the five
   the resolver ships (`cio`, `architect`, `developer`, `product-manager`,
   `engineering-manager`), when post-login routing resolves, then the user is routed to a
   safe fallback and the failure is logged — routing must never crash the sign-in flow or
   leave the user on a blank page.

## Non-functional requirements

- Security: routing is a usability affordance only and MUST NOT become the access control.
  Every endpoint keeps its server-side RBAC check; a user who forges a route still gets the
  same 403 from the API (`org_access` et al. unchanged). Routing never widens access.
- Performance: post-login routing adds no extra round-trip beyond the `GET /api/me` the
  shell already performs; it rides the persona resolver's existing 300s cache rather than
  introducing a second lookup.
- Observability: log the resolved persona and chosen destination on each routing decision,
  using the existing allowlist-keys discipline (no email, no token).
- Accessibility: the "dashboard not available yet" state meets WCAG AA and does not rely on
  colour alone to convey status.
- Design: `docs/design/schema.json` has no `AUTH` key and none of the six mockups shows an
  unshipped-dashboard or collapsed-denial state (verified against `docs/design/README.md`'s
  screen inventory) — raised per CLAUDE.md § Design system rather than designed here. Per
  PO decision (Decision log), the not-available state is a minimal, unstyled placeholder
  (persona name + fixed copy, no mockup-derived layout) until the persona's own dashboard
  story ships and supplies real markup for that route.

## Dependencies

- Upstream: AUTH-07 (`GET /api/me` — supplies `{name, persona}`; shipped), AUTH-02 (persona
  resolver, 3-tier + 300s cache; shipped), AUTH-03 (`rbac-checks` — the server-side gates
  this story must not duplicate or weaken; shipped).
- Downstream: ARC-01, EMD-01, DEV-01, PMD-01 each register their route with this story's
  persona→route map when they ship. Those four remain the owners of their page content; this
  story owns only the mapping and the not-yet-available state.

## Test mapping

- Unit: `apps/web` — persona→route resolution for all five personas, the unshipped-dashboard
  branch, and the resolver-failure fallback (vitest).
- Integration: `apps/web` — `/callback` hand-off lands each persona on its expected route
  (mocked `GET /api/me`).
- E2E: Playwright — sign in as a non-CIO persona and assert the not-available state rather
  than stacked access-denied panels; execution deferred to `/arh-validate-feature` per
  `docs/config/project-commands.yaml`.
- Manual: confirm against a real Keycloak session that switching a user's role changes their
  landing page after the persona cache's 300s TTL expires (or an app restart).

## Clarifications

None — both open questions were resolved with the product owner on 2026-09-18, before
validation. See § Decision log entries dated 2026-09-18 (placeholder route, QA scope).

## Decision log

- 2026-09-18 Placed in the `AUTH` epic rather than under any persona epic — the story owns
  sign-in-time routing and the persona→route map, which is cross-persona infrastructure, and
  `AUTH` already owns sign-in, persona resolution and RBAC. Placing it in `ARC`/`DEV`/`PMD`/
  `EMD` would have forced four copies of one decision.
- 2026-09-18 Reuses `GET /api/me` (AUTH-07) rather than adding a routing endpoint — the
  persona is already resolved and returned there, behind an existing cache.
- 2026-09-18 Scope deliberately excludes building any persona dashboard. ARC-01/EMD-01/
  DEV-01/PMD-01 keep that work; this story makes the routing correct whether or not those
  pages exist yet, which is why it can ship before them.
- 2026-09-18 AC-6 (collapse duplicate access-denied panels) folded in here rather than
  raised against OVW-01/OVW-04 — the stacked panels are a per-region rendering consequence
  visible only to non-CIO personas, which is exactly this story's audience. Neither shipped
  story is reopened.
- 2026-09-18 **Unshipped-persona landing = a dedicated per-persona route** (PO-resolved), not
  an inline state on a shared page. Each persona gets its real route from this story onward;
  today it renders the not-available state, and the persona's own dashboard story later
  replaces only what that route renders. Chosen so the persona→route map is written once here
  and never revisited — the inline-state alternative would have made every one of ARC-01/
  EMD-01/DEV-01/PMD-01 carry routing changes of its own.
- 2026-09-18 **No mockup covers the unshipped-dashboard or collapsed-denial states** (raised
  per CLAUDE.md § Design system, PO-resolved) — `docs/design/schema.json` has no `AUTH` key,
  and none of the six mockups' sections (`docs/design/README.md` screen inventory) shows a
  "not available yet" placeholder or a single collapsed access-denied panel. PO decision:
  ship both as minimal, unstyled placeholders (fixed copy, no mockup-derived layout) rather
  than invent a design; the persona's own dashboard story restyles its route when it ships.
- 2026-09-18 **QA is out of scope** (PO-resolved). `CLAUDE.md` § Personas lists six personas
  including QA, but the shipped resolver (AUTH-02) returns only five, so a QA persona cannot
  occur at runtime and routing one would be coding against an impossible input. AC-7's
  safe-fallback branch covers it if a sixth persona is ever added. Revisit when a QA dashboard
  story enters the RTM.
