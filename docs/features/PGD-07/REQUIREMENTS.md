# Feature: PGD-07 — Program Detail brand bar: signed-in identity block (shell retrofit)

## Problem

Program Detail (`/programs/[program_id]`) is the only dashboard page that skips
`PersonaDashboardShell` entirely — `ProgramDetailView.tsx` renders its own
`<div className={styles.wrapper}>` holding only `ProgramDetailHeader` +
`ProgramSummaryCards`. The entire `<!-- BRAND BAR -->` region (logo tile,
product name, tagline, signed-in identity block, sign-out control) is absent.
A signed-in user landing here after drilling in from Overview loses the brand
bar and cannot sign out without navigating back to a page that has one.

## Outcome

Every signed-in session on `/programs/<program_id>` sees the same brand bar
`/overview` already renders: logo tile, product name/tagline, and — once
`GET /api/me` resolves — the caller's own persona tag, subtitle, name/initials,
and a working sign-out control. The identity block always reflects the actual
signed-in persona (all five: cio, architect, developer, engineering-manager,
product-manager), never a hardcoded or sampled value. Program Detail stops
being the one page a user cannot sign out from.

## Constraints

- `PersonaDashboardShell`'s header region is gated on `program !== undefined`.
  `ProgramDetailHeader` already ships the mockup's `<!-- HEADER -->` region
  (avatar/name/type-chip/description) — the shell MUST be passed
  `program: undefined` explicitly, or that region double-renders (AC-2,
  `persona-shell` `program_detail_brand_bar`).
- `persona` and `signedInUser` are sourced only from `GET /api/me`
  (`session-identity-api`, AUTH-07) — never a page-side constant, never
  hardcoded to `cio` (AC-3, story NFR/Security).
- `jobTitle` is derived client-side from `PERSONA_DISPLAY[persona].jobTitle`
  (`apps/web/src/lib/composeSignedInUser.ts`) — never read off the `/api/me`
  wire, which ships `{name, persona}` only (`session-identity-api`,
  `MeResponse`, `extra="forbid"`).
- The sign-out control is the same `PersonaDashboardShell` control OVW-05
  ships — this story composes the shell, it does not fork or re-implement it
  (AC-9).
- Desktop-only design — the mockups carry no responsive breakpoints
  (`docs/design/README.md`); no mobile layout exists for this shell.
- One `GET /api/me` call per Program Detail server render, none on switcher
  reload — assumption, extending `session-identity-api`'s per-page-render
  perf note to this specific consumer (story NFR/Performance).

## Solution sketch

`apps/web/src/app/programs/[program_id]/page.tsx` adds a server-side
`GET /api/me` fetch, run concurrently with the existing program-detail fetch
via `Promise.all` (mirroring OVW-05's `overview/page.tsx` pattern), and passes
the resolved `persona`/`signedInUser` (or the persona-resolution-error
sentinel on failure) to `ProgramDetailView.tsx`. `ProgramDetailView` wraps its
existing `ProgramDetailHeader` + `ProgramSummaryCards` content in
`PersonaDashboardShell`, forwarding `persona`/`signedInUser` and passing
`program: undefined`. No new markup is authored — `PersonaDashboardShell`,
`composeSignedInUser`, and `meApi.fetchMe` are reused unchanged.

## Addressing Research Conditions

Research verdict GO-WITH-CONDITIONS (83/100). `docs/research/PGD-07.md` §
"Conditions for Plan" carries 4 numbered conditions:

- **C-1 (R1 — jobTitle wire leakage)**: PLAN.md must include a unit-test task
  for `composeSignedInUser` — fixture mocks a `meApi` response containing a
  decoy `jobTitle` key on the wire object; assert the composed `SignedInUser`
  omits it and `jobTitle` instead equals `PERSONA_DISPLAY[persona].jobTitle`.
- **C-2 (R5 — sign-out control placement)**: PLAN.md must include a focused
  unit-test task asserting the sign-out `<form action="/logout">` control
  renders in BOTH the populated-`signedInUser` branch AND the D-05 neutral-
  fallback (no `signedInUser`) branch of `PersonaDashboardShell` as rendered
  on Program Detail. This is AC-12 inherited from OVW-05, shipped untested —
  PGD-07 is the first consumer to close that gap.
- **C-3 (R8 — persona rendering)**: PLAN.md must include a unit-test task for
  `ProgramDetailView` verifying `jobTitle` and avatar colour derive from
  `PERSONA_DISPLAY`/`formatPersonaTag` and match the passed `persona` prop,
  parameterized across all five personas (cio, architect, developer,
  engineering-manager, product-manager).
- **C-4 (R3 — SessionExpiredError comment)**: PLAN.md's `Promise.all` handling
  in `page.tsx` must carry a code comment explaining why a `SessionExpiredError`
  thrown by EITHER the `/api/me` fetch or the program-detail fetch triggers the
  same `redirect("/login")` — referencing `tokenStore.refreshPromise` as the
  dedup guard that makes a single coordinated redirect correct rather than a
  race.

## Scope

**In:**
- `apps/web/src/app/programs/[program_id]/page.tsx`: add concurrent
  `GET /api/me` fetch via `meApi.fetchMe`, compose `SignedInUser` (or the
  persona-resolution-error sentinel), pass `persona`/`signedInUser` to
  `ProgramDetailView`.
- `apps/web/src/components/ProgramDetailView.tsx`: accept `persona?`/
  `signedInUser?` props, wrap existing content in `PersonaDashboardShell` with
  `program: undefined`.
- Brand bar (logo tile, product name, tagline), signed-in identity block
  (name/initials/persona tag/subtitle/jobTitle), and sign-out control on
  `/programs/<program_id>` — all via the existing, unmodified
  `PersonaDashboardShell`.
- Four research-condition tests (C-1..C-4 above).

**Out:**
- Any change to `PersonaDashboardShell.tsx`, `composeSignedInUser.ts`,
  `meApi.ts`, or `formatPersonaTag.ts` — all consumed as-is, frozen contracts.
- `ProgramDetailHeader` / `ProgramSummaryCards` — unmodified; this story adds
  a wrapper, not new header content (the mockup's `<!-- HEADER -->` region is
  already shipped by PGD-01).
- Any new observability event — no new telemetry (story NFR/Observability).
- Mobile/responsive layout — mockups are desktop-only.

## Functional requirements

FRs trace 1:1 to story ACs; see `docs/stories/PGD-07.md` for canonical
wording. New impl constraints introduced below:

**PGD-07-FR-1** — Concurrent fetch and error coordination *(extends AC-7 with:
exact mechanism)*

`page.tsx` issues `GET /api/me` and the existing program-detail fetch inside
one `Promise.all`, both wrapped in the same try/catch used for the existing
program-detail fetch. A `SessionExpiredError` from either fetch redirects to
`/login` — no new auth state, no partial-render on a persona-only failure
(AC-7). Per Research Condition C-4, the code carries a comment explaining the
coordinated-redirect rationale referencing `tokenStore.refreshPromise`.

**PGD-07-FR-2** — `program: undefined` enforcement *(extends AC-2 with: caller
obligation)*

`ProgramDetailView` calls `<PersonaDashboardShell program={undefined} ...>`
explicitly — never the real program object — so `PersonaDashboardShell`'s
`program !== undefined` header gate never fires here; `ProgramDetailHeader`
remains the sole renderer of the program header region.

**PGD-07-FR-3** — Persona-resolution failure handling *(extends AC-5 with:
sentinel mechanism)*

When `fetchMe()` does not return `status: "ok"` (403, unrecognized persona),
`page.tsx` passes the existing persona-resolution-error sentinel value to
`PersonaDashboardShell` (same mechanism OVW-05 established) rather than
omitting `persona` or guessing a value — the shell's own `PersonaTagError`
path renders the neutral "Persona unavailable" badge and `aria-live` region.

## Non-functional requirements

- Performance: Per `.claude/rules/performance-baseline.md`: the added
  `GET /api/me` fetch is server-side and parallelized via `Promise.all` with
  the existing program-detail fetch — no added sequential latency, one call
  per Program Detail render, timeout 5s (matches `meApi`/`overviewApi`
  convention). Story NFR: page render ≤3s under normal load, unchanged from
  PGD-01's existing budget.
- Security: Per `.claude/rules/security-baseline.md`: applies to the modified
  page/component. Feature-specific: identity block source is the bearer
  session only via `GET /api/me` — no page ever asserts a persona on the
  caller's behalf; persona-resolution failures fail closed (403 → neutral
  badge, never a guessed persona).
- Accessibility: Per `.claude/rules/accessibility-baseline.md`: applies to the
  brand bar and identity block on this page. WCAG AA, where feasible —
  mirrors the project NFR baseline other persona-shell-consuming stories cite
  (story NFR/Accessibility).
- Observability: N/A — no new log event. `GET /api/me`'s resolution-failure
  visibility is already owned by `persona-resolver`'s existing events (AUTH-07
  Decision log); this story adds no telemetry of its own, consistent with
  SHP-01's precedent that the presentational shell emits none.

## Screen inventory

Scoped to the brand bar region being retrofitted onto the existing Program
Detail screen (`docs/design/mockups/Program Detail.html`, PGD epic per
`docs/design/schema.json`). The brand-bar/identity-block markup itself is
drawn from `docs/design/mockups/CIO Portfolio Dashboard.html` (OVW epic) —
`ProgramDetailView` gains that same shared region, not a new one; the Program
Detail mockup's HEADER/summary-card regions below it are unchanged (PGD-01,
out of scope here).

| Screen | Route | Render | Primary purpose | States | Story ACs covered |
|---|---|---|---|---|---|
| Program Detail brand bar (static) | /programs/[program_id] | server (initial load) | Logo tile, "AgentRise Harness" product name, "AI SDLC Governance" tagline — renders unconditionally, even before persona resolves | Populated (always, static) | AC-1, AC-4 |
| Program Detail identity block | /programs/[program_id] | server (initial load), resolved via concurrent `GET /api/me` | Persona tag/subtitle, signed-in user name + initials avatar, `jobTitle` derived from `PERSONA_DISPLAY` | Loading (persona unresolved — block absent, no skeleton) / Populated (persona + name resolved) / Populated-neutral (persona resolved, `signedInUser.name` null — neutral gray circle) / Error (403 or unrecognized persona — neutral "Persona unavailable" badge + `aria-live` announcement) | AC-3, AC-4, AC-5, AC-6 |
| Program Detail sign-out control | /programs/[program_id] (sibling of identity block within brand bar) | server (zero-JS form) | `<form action="/logout">` sign-out button, same `PersonaDashboardShell` control as `/overview` | Populated (renders whenever `!isLoading`, i.e. in both the populated and neutral-fallback identity branches) / Absent (persona still loading) | AC-8, AC-9 |
| Program Detail header + summary cards (unchanged) | /programs/[program_id] | server (initial load) + client (switcher reload) | Existing `ProgramDetailHeader` + `ProgramSummaryCards`, now rendered as `PersonaDashboardShell` children with `program: undefined` passed to the shell itself | Populated / Loading / Error (unchanged from PGD-01) | AC-2 |

## Visual spec

See [DESIGN.md](./DESIGN.md) — brand bar, identity block, sign-out control and
the loading/populated/error states, specified against
`docs/design/mockups/Program Detail.html`.

## Rollout plan

- **Strategy**: bang-bang — additive shell wrap around existing content,
  reuses frozen, already-shipped components (`PersonaDashboardShell`,
  `composeSignedInUser`, `meApi`); no existing response contract changes.
- **Feature flag**: none.
- **Backout plan**: revert the `PersonaDashboardShell` wrap in
  `ProgramDetailView.tsx` and the added `GET /api/me` fetch in `page.tsx`; no
  schema or data migration to unwind.
- **Success signal**: Program Detail server responses continue to meet the
  ≤3s render budget with the added concurrent fetch; zero regressions in
  `ProgramDetailHeader`/`ProgramSummaryCards` rendering; all four research
  condition tests (C-1..C-4) passing before merge.

## Documentation requirements

- **README updates**: none — no new endpoint or route; `/programs/[program_id]`
  is already documented via PGD-01.
- **Runbook**: none.
- **API reference**: none — consumes the existing, already-documented
  `GET /api/me` (`README.md` § API table, AUTH-07 row).
- **Inline code comments**: `apps/web/src/app/programs/[program_id]/page.tsx`
  — comment on the `Promise.all` block explaining the coordinated
  `SessionExpiredError` redirect (Research Condition C-4/FR-1).
  `apps/web/src/components/ProgramDetailView.tsx` — comment noting
  `program: undefined` is deliberate, not an omission (FR-2).
- **Examples / how-to**: none.

## Open questions

Decisions logged in `docs/stories/PGD-07.md` § Decision log.

## Approvals

| Role | Reviewer | Date | Verdict |
|---|---|---|---|
| PO (Feature Summary, FRs, User Flows) | Pratik Pawar | 2026-09-16 | APPROVE |
| Designer (`DESIGN.md` UI specs) | Pratik Pawar | 2026-09-16 | APPROVE |
| BA (Edge cases, open questions, test cases) | Pratik Pawar | 2026-09-16 | APPROVE |

Recorded at the `/arh-plan-requirements` Product Gate, single-approver mode.

Approved with one known deviation, accepted not fixed: `DQA-1-preauth-contrast` —
the inherited `#8a93a1` tagline / `jobTitle` grey is 3.10:1 and fails the WCAG AA
target stated in `## Non-functional requirements`. It now reaches a fifth surface
(`/programs/<program_id>`). Darkening the token has blast radius across all six
dashboards, so it stays OVW-05's carry-forward rather than becoming PGD-07 scope.
