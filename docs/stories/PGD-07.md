# Story: PGD-07 — Program Detail brand bar: signed-in identity block (shell retrofit)

**Epic**: PGD
**Status**: Validated
**Priority**: P1
**Owner**: —
**Updated**: 2026-09-10
**Tracker**: pratikpawar009/Dashboard#277 (https://github.com/pratikpawar009/Dashboard/issues/277)

## User story

As a signed-in dashboard user viewing Program Detail (any persona, not only the CIO), I want the same product brand bar and my own signed-in identity block that every other dashboard page renders, so that Program Detail stops being the only page missing that region and never shows a hardcoded or wrong identity.

## Acceptance criteria

1. Given a signed-in user navigates to `/programs/<program_id>`, when the page renders, then the entire `<!-- BRAND BAR -->` region (logo tile, "AgentRise Harness" product name, "AI SDLC Governance" tagline) appears above `ProgramDetailHeader` — currently absent in full, since `ProgramDetailView.tsx` renders only its own `<div className={styles.wrapper}>` holding `ProgramDetailHeader` + `ProgramSummaryCards` (RTM Decisions 2026-09-10, `api.md` `persona-shell` `program_detail_brand_bar`).
2. Given `ProgramDetailView`'s existing content is wrapped in `PersonaDashboardShell`, when the shell is composed, then it is passed `program: undefined` explicitly, never the real program object — `PersonaDashboardShell`'s header region is gated on `program !== undefined`, and `ProgramDetailHeader` already ships the mockup's `<!-- HEADER -->` region (program avatar/name/type-chip/description); passing a real `program` would double-render it (sourced, `persona-shell` `program_detail_brand_bar`).
3. Given `GET /api/me` (`session-identity-api`) resolves successfully, when the shell composes, then `persona` and `signedInUser` are populated from that response — never a page-side constant, never hardcoded to `cio` — and the identity block renders the ACTUAL signed-in persona's tag/subtitle/avatar colour and `jobTitle`, one of: `cio` → "Chief Information Officer", `architect` → "Architect", `developer` → "Developer", `engineering-manager` → "Engineering Manager", `product-manager` → "Product Manager" (sourced, `persona-shell` `job_title_source_note`). The mockup's sampled `Elena Vasquez`/CIO values never ship as fallback copy or a default.
4. Given `persona` has not yet resolved (`GET /api/me` in flight), when the page renders, then only the static brand bar (logo/name/tagline) shows — no persona tag, subtitle, program context, or identity block, and no skeleton (sourced, `persona-shell` `states.loading`).
5. Given `GET /api/me` returns `403` (persona-resolution failure) or an otherwise-unrecognized persona value reaches the shell, then the neutral gray "Persona unavailable" badge renders in place of the persona tag, plus a visually-hidden `aria-live="assertive"` announcement reading "Unable to load your dashboard view." (sourced, `persona-shell` `states.error`, `session-identity-api` `errors`).
6. Given `signedInUser.name` is `null` (fallback chain exhausted — e.g. a dev-bypass session), when the identity block renders, then it shows the shell's existing neutral fallback (plain gray circle, no initials, `aria-hidden`), never blank or broken text (sourced, `persona-shell` `states.populated`).
7. Given `GET /api/me` returns `401` (missing/invalid bearer), then the existing unauthorized handling for this route applies — no new auth state is invented for this fetch (per `session-identity-api` `errors`; consistent with `page.tsx`'s existing `SessionExpiredError` → `/login` redirect for the program-detail fetch).

## Non-functional requirements

- Performance: adds exactly one `GET /api/me` call per Program Detail server render, none on switcher reload — assumption, extending `session-identity-api`'s own "one call per page render" perf note (api.md) to this specific consumer, which the contract states for the endpoint generally but not per-consumer call count.
- Security: the identity block's source is the bearer session only, never a page-side constant — a page must not assert `persona: 'cio'` on the caller's behalf (sourced, `session-identity-api` `persona` note, same rule stated for `/overview`). Persona-resolution failures fail closed (`403` → neutral badge, never a guessed persona; per `session-identity-api` `errors`).
- Accessibility: WCAG AA, where feasible — assumption, mirrors the project NFR baseline other PGD/persona-shell stories cite (no story-specific target given here).
- Observability: N/A — no new log event. `GET /api/me`'s own resolution-failure visibility is already owned by `persona-resolver`'s existing events (per AUTH-07's Decision log); this story adds no telemetry of its own, consistent with `SHP-01`'s precedent that the presentational shell emits none.

## Dependencies

- Upstream: AUTH-07 via `session-identity-api` (`docs/requirements/api.md#session-identity-api`) — `GET /api/me` → `{name, persona}`, frozen shape, buildable against a stub. OVW-05 via `persona-shell` (`docs/requirements/api.md#persona-shell`) — specifically its `cio_persona_note`, which makes `cio` a fifth renderable persona with its own `PERSONA_DISPLAY` entry (tag `CIO / CXO`, colour `#0f1a2e`, `jobTitle`); without it a signed-in CIO viewing Program Detail hits the shell's error badge rather than a rendered identity block. Both dependencies are via frozen contract sections, not either sibling's code (RTM Decisions 2026-09-10 splitting-out rationale) — this story builds against the stubs.
- Downstream: none — `PGD-07` produces no new contract; it is a leaf consumer of `session-identity-api` and `persona-shell`.

## Test mapping

- E2E: NA — no e2e framework configured yet (`test_e2e` unset in `docs/config/project-commands.yaml`, per ADR-0001).
- Unit: `apps/web/src/components/ProgramDetailView.tsx` (wraps existing content in `PersonaDashboardShell` with `program: undefined`, threads `persona`/`signedInUser` props); `apps/web/src/app/programs/[program_id]/page.tsx` (server-side `GET /api/me` fetch alongside the existing program-detail fetch); `PersonaDashboardShell.tsx`/`PersonaDashboardShell.test.tsx` (existing, unchanged — reused as-is, no new markup authored per `persona-shell` `identity_block_unblocked`).
- Manual: NA — covered by unit tests; no e2e framework to add manual-only coverage for.

## Clarifications

## Decision log

- 2026-09-10 One `GET /api/me` call per Program Detail render, none on switcher reload (NFR/Performance): assumption — extends `session-identity-api`'s per-page-render perf note to this consumer; the contract doesn't state a per-consumer call count.
- 2026-09-10 Accessibility target WCAG AA (NFR): assumption — no story-specific target given; mirrors the project's other persona-shell-consuming stories (e.g. SHP-01).
- 2026-09-10 No new observability event (NFR/Observability): assumption — mirrors SHP-01's precedent that the presentational shell emits no telemetry of its own; resolution-failure visibility is already owned by the contracts this story consumes.
