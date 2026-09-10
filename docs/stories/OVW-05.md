# Story: OVW-05 — CIO shell regions: signed-in identity block + org page-title header

**Epic**: OVW
**Status**: Validated
**Priority**: P1
**Owner**: —
**Updated**: 2026-09-10
**Tracker**: pratikpawar009/Dashboard#276 (https://github.com/pratikpawar009/Dashboard/issues/276)

## User story

As a CIO, I want the Adoption Overview page's brand bar to show who I'm signed in as and its header to show the "Adoption Overview" title with my CIO context, so that I can confirm my identity and that I'm viewing the org-wide CIO dashboard rather than a persona view.

## Acceptance criteria

1. Given `apps/web/src/types/persona.ts`, when `VALID_PERSONAS` is inspected, then it includes `"cio"` as a fifth entry alongside the existing four (`architect`, `developer`, `product-manager`, `engineering-manager`) (`persona-shell` `cio_persona_note`).
2. Given `apps/web/src/lib/formatPersonaTag.ts`'s `PERSONA_DISPLAY` map, when `formatPersonaTag("cio")` is called, then it returns `{ tag: "CIO / CXO", subtitle: "Organization-wide AI-in-SDLC adoption, spend & impact", color: "#0f1a2e", background: "#e6e9ef" }` instead of throwing `PersonaTagError` (sourced: decoded `dashboards/CIO Portfolio Dashboard.html` brand-bar pill/avatar and header subtitle; `persona-shell` `cio_persona_note`).
3. Given the `PersonaDisplay` shape, when any of the five `PERSONA_DISPLAY` entries is inspected, then each carries a `jobTitle` field with a plain role name — `cio`: "Chief Information Officer", `architect`: "Architect", `developer`: "Developer", `engineering-manager`: "Engineering Manager", `product-manager`: "Product Manager" — never the mockups' seniority-bearing literals "Principal Architect" (Architect mockup) or "Senior Developer" (Developer mockup), which this story deliberately supersedes because the system holds no seniority data anywhere (`persona-shell` `job_title_source_note`/`job_title_divergence_note`).
4. Given `formatPersonaTag.ts`'s `PersonaTagError` docstring and `formatPersonaTag`'s own docstring, when this story ships, then the premise "the CIO Portfolio mockup has no persona tag/subtitle region at all — so a `cio` value reaching this function is an invariant violation, not a fifth persona to render" is removed and replaced with text reflecting `cio` as a valid, renderable persona (`persona-shell` `cio_persona_note`; verified false against the decoded mockup — CIO's brand bar/header are structurally identical to Architect's).
5. Given a signed-in CIO session, when `AdoptionOverview` renders, then it calls `GET /api/me` (`session-identity-api`) server-side and passes the resulting `persona` to `PersonaDashboardShell` — never a hardcoded `persona="cio"` literal — which ends the shell's permanently-`isLoading` state that today's `persona`-omitting call produces.
6. Given `GET /api/me` returns a non-null `name`, when `AdoptionOverview` composes the shell's `signedInUser` prop, then it passes `{ name, jobTitle: PERSONA_DISPLAY[persona].jobTitle }` and the brand bar renders that name, that job title, and a 34×34 circular initials avatar (`border-radius:50%`) on `background:#0f1a2e` for a `cio` persona.
7. Given `GET /api/me` returns `name: null` (e.g. a `dev-bypass` token with no profile claims), when `AdoptionOverview` composes `signedInUser`, then it passes `undefined` rather than a fabricated name, and the shell's existing neutral fallback (a plain gray circle, no initials, `aria-hidden`) renders — the mockup's sample name `Elena Vasquez` never ships as fallback copy.
8. Given `PersonaDashboardShell.tsx`, when this story ships, then it exposes a new optional prop that carries the composing page's title (e.g. `pageTitle?: string`) and, when that prop is defined together with a resolved `persona` and `program === undefined`, renders a second header composition — the page title (`font-size:19px; font-weight:700; letter-spacing:-.3px`) plus the persona pill (`formatPersonaTag(persona).tag`) on one line, then the persona subtitle beneath (`font-size:12.5px; color:#7a828f; font-weight:500`) — selected purely by prop presence, mutually exclusive with the existing `program !== undefined` header-region variant, and with no `persona === 'cio'` (or any persona-literal) conditional added inside `PersonaDashboardShell.tsx` (`persona-shell` `org_header_region`).
9. Given a CIO session, when `AdoptionOverview` passes `pageTitle="Adoption Overview"` and omits `program`, then the header renders title "Adoption Overview", pill "CIO / CXO" (`font-size:11px; font-weight:700; color:#0f1a2e; background:#e6e9ef; padding:3px 9px; border-radius:20px`), and subtitle "Organization-wide AI-in-SDLC adoption, spend & impact" beneath — matching the decoded `HEADER` region of `dashboards/CIO Portfolio Dashboard.html`.
10. Given `persona === undefined` (not yet resolved), when `PersonaDashboardShell` renders, then neither the identity block nor either header variant renders — only the brand bar's static left half (logo tile + product name/tagline) — unchanged from the shell's existing FR-5 no-flash/no-skeleton rule.
11. Given `apps/web/src/types/persona.ts` and `PersonaDashboardShell.tsx`'s `SignedInUser`/`signedInUser` PROVISIONAL docstrings (pending "the AUTH-01 session-contract amendment"), when this story ships, then those docstrings are updated to reflect resolution without a rename: `name` arrives from `session-identity-api` under that exact field name, and `jobTitle` is composed frontend-side from `PERSONA_DISPLAY[persona].jobTitle` — the `SHP-01 D-01` field-name isolation adapter is left intact, not exercised.

## Non-functional requirements

- Performance: page render issues one additional `GET /api/me` call alongside the existing `GET /api/overview/summary` call; total render must still meet the page's existing ≤3s budget (NFR-001, per OVW-01) — no separate per-call budget is set for `/api/me` — assumption, no source gives one (Decision log). `session-identity-api`'s underlying `resolve()` is already process-cached 300s (sourced, `session-identity-api` `perf`), so repeat loads inside that window add no new backend latency.
- Security: `/overview` stays CIO-gated by `org_access` (AUTH-03, sourced OVW-01 AC-3) — this story adds no new route. `AdoptionOverview` must never hardcode `persona="cio"`; the value is always read from `session-identity-api`'s server-confirmed `persona` field (sourced, RTM Decisions 2026-09-10) — a page-side constant would assert an identity the server never confirmed.
- Accessibility: WCAG AA (NFR-008, per OVW-01 precedent) — the neutral-avatar fallback stays `aria-hidden="true"` (AC-7) and the new org-header composition adds no new interactive control, preserving the shell's existing FR-5 no-flash/no-skeleton behavior (sourced, `persona-shell` states).
- Observability: no new logging event is introduced — `rbac_check_org_access` (OVW-01) is unaffected by this story; `session-identity-api`'s own 401/403 logging is AUTH-07's concern, not this story's (sourced, contract `errors`).

## Dependencies

- Upstream: `AUTH-07` via `session-identity-api` (`docs/requirements/api.md#session-identity-api`) — frozen `GET /api/me` → `{name, persona}` shape; unshipped, but this story builds and tests against the frozen two-field stub, not AUTH-07's code (RTM Decisions 2026-09-10). `SHP-01` via `persona-shell` (`docs/requirements/api.md#persona-shell`) — shipped `PersonaDashboardShell.tsx`/`formatPersonaTag.ts`/`apps/web/src/types/persona.ts`, which this story extends as co-producer (`produced_by: [SHP-01, OVW-05]`).
- Downstream: `PGD-07` (Program Detail brand bar retrofit) depends on this story's `cio` persona-map addition via `session-identity-api`/`persona-shell` (both frozen contracts) before a CIO viewing Program Detail renders correctly instead of the relocated "Persona unavailable" badge.

## Test mapping

- E2E: N/A — no e2e framework configured (`test_e2e` empty, `docs/config/project-commands.yaml`).
- Unit: `apps/web/src/lib/formatPersonaTag.ts`/`formatPersonaTag.test.ts` (AC-1..4, `cio` entry + `jobTitle` field on all 5 entries); `apps/web/src/types/persona.ts` (AC-1, `VALID_PERSONAS`); `apps/web/src/components/PersonaDashboardShell.tsx`/`PersonaDashboardShell.test.tsx` (AC-5..10, org-header variant, mutual exclusivity with the program-header variant, `isLoading` gate); `apps/web/src/components/AdoptionOverview.tsx`/`AdoptionOverview.test.tsx` (AC-5..7/9, `GET /api/me` wiring, `pageTitle` prop, null-name fallback).
- Manual: visual diff against the decoded `dashboards/CIO Portfolio Dashboard.html` `BRAND BAR`/`HEADER` regions — `design_check` is empty in `docs/config/project-commands.yaml` (no automated visual/a11y tool wired yet).

## Clarifications

## Decision log

- 2026-09-10 `cio` admitted as a fifth persona; `PERSONA_DISPLAY.cio` = `{tag: "CIO / CXO", color: "#0f1a2e", background: "#e6e9ef", jobTitle: "Chief Information Officer", subtitle: "Organization-wide AI-in-SDLC adoption, spend & impact"}` (per decoded `dashboards/CIO Portfolio Dashboard.html`, RTM Decisions 2026-09-10, `persona-shell` `cio_persona_note`/`job_title_source_note`).
- 2026-09-10 Job titles are plain role names, not the mockup literals, for all five personas — `architect`: "Architect" (supersedes mockup's "Principal Architect"), `developer`: "Developer" (supersedes mockup's "Senior Developer") — per `persona-shell` `job_title_divergence_note`, user-confirmed 2026-09-10.
- 2026-09-10 New shell prop name for the org header's page title: `pageTitle` — assumption; the contract (`persona-shell` `org_header_region`) specifies the title is "a prop from the composing page" but names no prop identifier.
- 2026-09-10 `GET /api/me` is called server-side (page/route level), mirroring `AdoptionOverview.tsx`'s existing `lib/overviewApi.ts`/`tokenStore.callWithAuth()` pattern for `overview-summary-api` — assumption; no new Next.js proxy route is added since the call never reaches client-side JS, consistent with `docs/adr/0008-client-side-auth-route-handler-proxy.md`. Source does not state the fetch location explicitly.
- 2026-09-10 No dedicated performance budget for the added `GET /api/me` call — assumption; it shares the page's existing ≤3s render budget (NFR-001, OVW-01) rather than getting its own number, since no source gives one.
