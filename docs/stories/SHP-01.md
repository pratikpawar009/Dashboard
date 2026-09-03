# Story: SHP-01 — Persona header/context shell

**Epic**: SHP
**Status**: Validated
**Priority**: P1
**Owner**: —
**Updated**: 2026-08-26
**Tracker**: pratikpawar009/Dashboard#29 (https://github.com/pratikpawar009/Dashboard/issues/29)
**Tracker Research**: pratikpawar009/Dashboard#187
**Tracker Plan Requirements**: pratikpawar009/Dashboard#188
**Tracker Plan Implementation**: pratikpawar009/Dashboard#193

## User story

As a signed-in Architect, Developer, Product Manager, or Engineering Manager, I want a shared header that shows who I am, what persona view I'm in, and which program is in scope, so that every persona dashboard orients me the same way without each dashboard re-implementing it.

## Acceptance criteria

1. Given a signed-in user viewing any of the four individual-persona dashboards (Architect, Developer, Product Manager, Engineering Manager), when the persona-shell renders, then it displays the product header "AgentRise Harness / AI SDLC Governance", the signed-in user's display identity and role (from the `session` contract), and a persona tag matching the persona resolved for that user: "Architect" | "Developer" | "Product Manager" | "Eng Manager" (per FR-SH-01).
2. Given a program object (icon, name, type, description) is supplied by the composing dashboard page, when the persona-shell renders, then it renders the program-context block with that icon, name, type tag, and description unchanged (per FR-SH-02).
3. Given the signed-in persona is one of architect, developer, product-manager, or engineering-manager, when the persona-shell renders, then the subtitle matches that persona exactly: "Architect overview", "Developer overview", "Product Manager overview", or "Engineering manager overview" (per FR-SH-03).
4. Given session or persona-resolver data has not yet resolved, or the persona-resolver raises (all 3 config sources empty for the role, per the `persona-resolver` contract), when the shell is asked to render, then it shows a neutral loading state while pending and a generic error state on raise — never a blank or mismatched persona tag.

## Non-functional requirements

- Performance: shell renders within 200ms of its props (session + persona-resolver output) being available — assumption, no source budget given for this static presentational component (distinct from NFR-002's 2s range-refresh budget, which covers data-fetching panels).
- Security: shell must not render persona-gated content (tag, subtitle) until both `session` and `persona-resolver` have resolved — avoids a flash of incorrect persona; displays the resolved persona tag, never the raw IdP role string, per the `persona-resolver` contract's output enum.
- Accessibility: WCAG AA, where feasible (per NFR-008).
- Observability: N/A — this presentational shell emits no telemetry of its own; session/persona-resolution logging (`persona_mapping_loaded`, etc.) is owned by the AUTH-01/AUTH-02 contracts it consumes.

## Dependencies

- Upstream: AUTH-01 via `session` contract (`docs/requirements/auth.md` `### session` — bearer-JWT-bridged session; decoded fields `user_id, email, role, groups`); AUTH-02 via `persona-resolver` contract (`docs/requirements/auth.md` `### persona-resolver` — resolves `session.role` to `persona: cio | architect | developer | product-manager | engineering-manager`, 5-minute cache, raises if all 3 sources are empty for the role).
- Downstream: ARC-01, DEV-01, PMD-01, EMD-01 — each composes this shell via the `persona-shell` contract (`docs/requirements/api.md` `### persona-shell`: `product_header, signed_in_user: { name, role }, persona_tag, subtitle, program_context: { icon, name, type, description }`).

## Test mapping

- E2E: N/A — no standalone flow file; covered indirectly by ARC-01/DEV-01/PMD-01/EMD-01 dashboard-compose E2E flows.
- Unit: `frontend/.../PersonaHeader.tsx`, `frontend/.../ProgramContext.tsx`, `frontend/.../PersonaDashboardShell.tsx`.
- Manual: N/A — fully coverable by unit/component tests.

## Clarifications

## Decision log

- 2026-08-26 Signed-in display identity: use `session.email` as the "name" surfaced in the header — assumption, the `session` contract exposes only `user_id, email, role, groups`, no separate display-name claim.
- 2026-08-26 Persona tag display strings: "Developer", "Product Manager", "Eng Manager" are sourced literals (PRD FR-DV-01/FR-PM-01/FR-EM-01 name these tags directly); "Architect" is an assumption inferred by the same naming pattern — FR-AR-01 doesn't give a literal tag string.
- 2026-08-26 `program_context` data source: passed in as props by the composing dashboard page (ARC-01/DEV-01/PMD-01/EMD-01) — assumption; SHP-01's Depends-on/Contract list (AUTH-01/AUTH-02 only) excludes any programs-data contract, so this shell is presentational-only for that field.
- 2026-08-26 Loading/error state on unresolved or raised session/persona data — assumption; PRD specifies the persona-resolver's raise condition but not the shell's UI response to it.
- 2026-08-26 Render performance budget (200ms) — assumption; no source budget exists for this presentational component.
- 2026-09-03 `signed_in_user` field naming in the amended persona-shell contract: `{ name, jobTitle }` (was `{ name, role }`) — assumption, logged during PRD drafting (`docs/features/SHP-01/REQUIREMENTS.md` FR-1); avoids overloading `role`, which the contract still uses for the raw IdP claim, distinct from job title and from the persona tag (research Risk 7). Superseded if the landed AUTH-01 amendment uses a different field name.
- 2026-09-03 Initials for a single-token display name: use that one letter only, no doubling — assumption, logged during PRD drafting (FR-3); neither the story nor the mockups' static markup covers the single-token case.
- 2026-09-03 Generic error-state fallback: neutral gray badge reading "Persona unavailable" in place of the persona tag, plus a visually-hidden `aria-live="assertive"` announcement ("Unable to load your dashboard view.") — assumption, logged during PRD drafting (FR-5); AC4 specifies the requirement, not the copy/markup.
