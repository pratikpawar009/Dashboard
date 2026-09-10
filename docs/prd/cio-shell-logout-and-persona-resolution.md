# CIO page shell, logout, and persona-role resolution

Source: findings from a live end-to-end session on 2026-09-10, after OVW-01 merged (PR #274).
Each item below was verified against the decoded design source or the running stack, and the
evidence is quoted inline. Decisions the user made during that session are marked **DECIDED**.

## 1. The Adoption Overview page is missing two regions the mockup shows

`dashboards/CIO Portfolio Dashboard.html`, decoded, has eight regions. OVW-01's `DESIGN.md`
scoped itself to `ORG SUMMARY` and `PROGRAM ADOPTION HEALTH` only. Two of the remaining six
belong to no story at all:

**a. `BRAND BAR` — signed-in identity block.** The right-hand side of the brand bar carries:

| Element | Mockup value (CIO) | Mockup value (Architect, for comparison) |
|---|---|---|
| Name | `Elena Vasquez` | `Devon Rao` |
| Job title | `Chief Information Officer` | `Principal Architect` |
| Avatar | 34px circle, `background:#0f1a2e`, white 13px/700 initials | same geometry, `background:#6a4fd0` |

The two brand bars are structurally identical. `#6a4fd0` is exactly
`PERSONA_DISPLAY.architect.color` in `apps/web/src/lib/formatPersonaTag.ts`, so the CIO is a
fifth persona with its own avatar colour, not a page that lacks a persona.

`PersonaDashboardShell` already implements this block, but gates it on
`persona !== undefined`. `AdoptionOverview` omits `persona` entirely (OVW-01 D-04), so
`isLoading` is permanently true and the block never renders.

**b. `HEADER` — page-title region.** Rendered beneath the brand bar, sticky:

- Title `Adoption Overview`, `font-size:19px; font-weight:700; letter-spacing:-.3px`
- Pill `CIO / CXO`, `font-size:11px; font-weight:700; color:#0f1a2e; background:#e6e9ef; padding:3px 9px; border-radius:20px`
- Subtitle `Organization-wide AI-in-SDLC adoption, spend & impact`, `font-size:12.5px; color:#7a828f; font-weight:500`

`PersonaDashboardShell` gates this whole region on `program !== undefined`, which is
structurally unsatisfiable for an org-level page that has no single program. So the shell
cannot render it today even if asked.

**The blocking premise to correct.** `formatPersonaTag()`'s docstring asserts: "The shell never
composes the CIO dashboard — the CIO Portfolio mockup has no persona tag/subtitle region at all
— so a `cio` value reaching this function is an invariant violation, not a fifth persona to
render." That is factually wrong about the mockup, and on the strength of it `cio` was left out
of `VALID_PERSONAS`. Passing `persona="cio"` today renders a "Persona unavailable" badge and a
neutral-grey avatar instead of the `CIO / CXO` pill and the `#0f1a2e` avatar.

**Unresolved: where `jobTitle` comes from.** `SignedInUser {name, jobTitle}` is marked
PROVISIONAL in `apps/web/src/types/persona.ts`, pending the AUTH-01 session-contract amendment
(SHP-01 constraint C-1). `CurrentUser` exposes `email`, `role`, `groups` and `programs` — no
`name`, no `jobTitle`. `Chief Information Officer` is a job title, not a persona tag, so it is
not derivable from `PERSONA_DISPLAY`. Candidate sources: an OIDC `name`/profile claim, the
`.harness/program.yaml` roster (`team[].name` / `team[].role`), or a persona→title constant.
This choice changes the response shape and must be decided, not assumed.

## 2. Logout does not exist anywhere — and it is app-wide, not a CIO concern

No occurrence of logout / signout in `apps/web/src`, `services/api/app`,
`docs/requirements`, `docs/stories` or `docs/prd`. No story owns it. Users authenticate through
Keycloak and have no way to end the session.

**Scope is the whole dashboard, not the Adoption Overview page.** This item is listed in the
same document as §1 only because both surfaced in one session; it is not part of, or blocked
by, the CIO shell work. What logout acts on is app-wide by construction:

- the `dashboard_session` cookie is written at `path: "/"` by
  `apps/web/src/lib/tokenStore.ts` and is the single session for every route;
- every authenticated page reads it through the same `callWithAuth()` path;
- the brand bar that would eventually host a control is the shared
  `PersonaDashboardShell` chrome used by all four persona dashboards, Program Detail and
  Overview alike.

So logout must end the session for **every** dashboard page — the four persona dashboards
(ARC-01/DEV-01/PMD-01/EMD-01), Program Detail (PGD-01) and Adoption Overview (OVW-01) — and
must not be implemented per-page or per-persona.

It is absent from the design: none of the six mockups' brand bars contain an `<a>`, a
`<button>`, or a `cursor:pointer` — the signed-in identity is display-only. `CLAUDE.md`
forbids inventing UI the mockups do not show.

**DECIDED (user, 2026-09-10): route-only, no new UI.** A `/logout` Next.js Route Handler that
clears the `dashboard_session` cookie and redirects to Keycloak's `end_session_endpoint`,
reachable by URL from anywhere in the app. No visual control is added, so nothing is invented;
placing a control in the shared brand bar stays open for a later story once a mockup covers it.
Because the control is deferred but the capability is not, the route must work standalone —
it cannot assume a caller that supplies state.

## 3. Persona role resolution depends on claim array order and letter case

`_resolve_role` in `services/api/app/core/auth.py` filters Keycloak system roles, then returns
**the first surviving entry of `realm_access.roles` in original list order**. Keycloak does not
guarantee the ordering of that array.

Observed live on 2026-09-10: a real user's token carried
`realm_access.roles = ['Architect', 'Developer', 'developer']`. Whichever entry happens to come
first decides the persona, so the same user can resolve to a different persona — and therefore a
different dashboard — between logins, with no change to their account.

Two compounding problems:

- **Case sensitivity.** All three resolver tiers match exactly. `Architect` does not match the
  Tier-2 `architect: architect` entry, so a correctly-provisioned user fails closed.
- **Indistinguishable failure.** The result was `rbac_check_org_access outcome=denied` with no
  `persona` field and no `persona_mapping_loaded` line — identical to a genuinely unmapped
  role. Nothing in the log says "a role was present but matched no tier."

Note the realm also holds both `Developer` and `developer` as separate roles, so
near-duplicate names are a live condition, not hypothetical.

## Out of scope for this intake

`README.md` § "Keycloak client requirements" omits the **Audience mapper** that the API's own
`aud` check requires (`_claims_options` in `services/api/app/core/auth.py` enforces
`aud == OIDC_CLIENT_ID`, and Keycloak access tokens carry the client id in `azp`, not `aud`,
without that mapper). Confirmed live: a real token arrived with `aud = None`,
`azp = 'harness-dashboard'`, and every protected route returned 401 until the mapper was added.
**DECIDED (user, 2026-09-10): fixed directly as a documentation change, not run through
intake.**
