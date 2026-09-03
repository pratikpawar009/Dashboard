# Research Assessment: SHP-01 — Persona header/context shell

**Story ID**: SHP-01
**Epic**: SHP
**Priority**: P1
**Upstream dependencies**: AUTH-01 (`session` contract), AUTH-02 (`persona-resolver` contract)
**Downstream dependencies**: ARC-01, DEV-01, PMD-01, EMD-01 (all consume `persona-shell` as a shared component)
**Assessment Date**: 2026-09-03
**Assessed by**: Claude Code Research Agent

---

## Upstream Dependency Summary

**Both upstream dependencies complete and ready:**

- **AUTH-01** (research verdict: GO-WITH-CONDITIONS, phase: review): provides the `session` contract at `docs/requirements/auth.md` § session. Implementation complete: bearer-JWT validation, role parsing from Keycloak's realm_access.roles, program-group parsing with configurable prefix. `app/core/auth.py::get_current_user()` returns `CurrentUser` with fields `user_id: str, email: str, role: str, groups: list[str]`. Frontend will receive this via Authorization header on every API call.

- **AUTH-02** (research verdict: GO-WITH-CONDITIONS, phase: security-reviewed): provides the `persona-resolver` contract at `docs/requirements/auth.md` § persona-resolver. Implementation complete: 3-tier (env-JSON, YAML file, Postgres), 5-minute per-role cache, resolves `session.role` to one of `{cio, architect, developer, product-manager, engineering-manager}`. Fails closed (raises `PersonaNotFoundError` if all tiers miss). Accessible via `app.state.persona_resolver.resolve(role: str)` — an async method routes must call.

**No architectural blockers.** Both session and persona-resolver are async-ready FastAPI services. The shell is presentational-only (renders what it receives); it does not directly call either backend service.

---

## Exploration Log

### Frontend Codebase State
- **Working directory**: `/Users/pratik.pawar/Desktop/dashboard` (clean main branch)
- **Frontend stack**: Next.js 15.5.24 (App Router), React 19.1.0, TypeScript 5.x (strict mode), pnpm, vitest
- **Current routes**: `apps/web/src/app/layout.tsx` (root layout), `apps/web/src/app/page.tsx` (home, scaffold placeholder)
- **No session/auth plumbing**: 
  - No NextAuth.js or other session provider installed
  - No `src/lib/` or `src/api/` directories for client-side fetching
  - No environment/context for session data
  - No state management library (Redux/Zustand/TanStack Query/SWR)
  - Test file exists (`src/smoke.test.ts`) but is a trivial smoke test
- **API contract surface**: None yet — no fetch calls to FastAPI backend exist in the codebase

### Design Mockup Analysis

The four dashboard mockups (Architect, Developer, Product Manager, Engineering Manager) contain an identical **header/persona-shell structure** with the following elements (extracted and cross-checked):

#### Section 1: Top Navigation Bar (Lines 375-385 in each mockup)
- **Product branding**: "AgentRise Harness" (size 15px, weight 800) + "AI SDLC Governance" subtitle (size 10.5px, gray #8a93a1)
- **Signed-in user block** — three displayed values: a human **display name** ("Devon Rao", "Maya Chen", "Noah Kim", "Aisha Bello"), a free-text **job title** ("Principal Architect", "Senior Developer", "Product Manager", "Engineering Manager"), and **initials** in a 34x34px persona-coloured circle ("DR", "MC", "NK", "AB"). The job title is NOT the `session.role` IdP role claim (which AUTH-02 keys its persona map on) and NOT the persona tag — "Principal Architect" vs role-claim vs persona `architect` are three distinct values. The initials appear in neither the story nor the `persona-shell` contract's field list. See Risk 1a.
- **Binding status (decisive)**: this entire block is **static literal text — no `{{ }}` bindings**, unlike the program-context block below it. Same for the persona tag and subtitle. Only `program_context` is actually bound (`{{ prog.avatar }}`, `{{ prog.avatarStyle }}`, `{{ prog.name }}`, `{{ prog.typeChip }}`, `{{ prog.ptype }}`, `{{ prog.desc }}`). Consequence: the mockups settle the *program-context* shape authoritatively, but they do **not** settle where the identity values or the persona strings come from — those are design placeholders, so the source must be decided, not read off the mockup.
- **Style note**: blurred header (`backdrop-filter:blur(8px)`), sticky positioning, light background `#ffffffcc`

_Region boundary: the signed-in-user bar sits **before** the `<!-- HEADER -->` comment; the persona tag, subtitle and program context sit inside the `<header>` element after it. The mockup has two distinct regions where the story's AC1 describes one shell — a component-boundary question for plan-implementation, not a blocker._

#### Section 2: Header / Persona Context (Lines 387-403 in each mockup)
- **Persona tag**: badge with persona name + background color
  - Architect: `<span>Architect</span>` | color #6a4fd0 | bg #f0edfb
  - Developer: `<span>Developer</span>` | color #2a6fdb | bg #e9f1fd
  - Product Manager: `<span>Product Manager</span>` | color #d97757 | bg #fdefe9
  - Eng Manager: `<span>Eng Manager</span>` | color #1f8a5b | bg #eaf6ef
- **Subtitle**: "Architect overview" | "Developer overview" | "Product Manager overview" | "Engineering manager overview" (note: lowercase 'm' in "Engineering manager overview")
- **Program context block**: icon/avatar (`{{ prog.avatar }}` or `{{ proj.avatar }}`), name (`{{ prog.name }}`), type chip (`{{ prog.ptype }}`), description (`{{ prog.desc }}`)

#### Cross-Mockup Consistency
- **Architect/Developer/Product Manager**: byte-identical header layout; differ only in persona tag color and subtitle text
- **Engineering Manager**: slight variation — uses `proj.*` variable names instead of `prog.*` (lines 394, 397-400); "Switch program" dropdown visible below the context block (lines 402-404) — NOT present in the other three
- **Story claim mismatch risk**: story says persona tags are "Architect" | "Developer" | "Product Manager" | "Eng Manager", and mockups confirm all four; story says subtitles match those exactly, and mockups confirm; story lists no variant between EMD and others, but EMD mockup has an extra "Switch program" control

### Backend Contracts & Serialization

**session contract** (`docs/requirements/auth.md` § session):
- Produced by: AUTH-01, available in every authenticated request via `app/core/auth.py::get_current_user()`
- Fields: `user_id: str, email: str, role: str, groups: list[str]`
- Note: the contract specifies `email` field; no separate `display_name` field exists — story's Decision log (line 43) correctly notes this assumption

**persona-resolver contract** (`docs/requirements/auth.md` § persona-resolver):
- Produced by: AUTH-02, instance on `app.state.persona_resolver`
- Method: `async def resolve(self, role: str) -> str`, returns one of `{cio, architect, developer, product-manager, engineering-manager}` (or any custom ops-configured value)
- Note: output is always one of those five enums; no hardcoded tie to display strings — the shell must translate `engineer` → "Eng Manager", `architect` → "Architect", etc., per the mockup contract

### Pattern Skills Baseline (G15 caveat)
- **next-patterns**: Filled body, covers App Router conventions
- **nextjs-patterns**: Filled body, documents Next.js 15 + React 19 + Turbopack specifics
- **typescript-patterns**: Filled body, enforces `strict: true`, path aliases `@/*`
- All three relevant frameworks have verified pattern guidance

---

## Pattern Map

### Existing Code to Extend
- **`apps/web/src/app/layout.tsx`** — extend root layout to add a session provider / context wrapper (see risk register, Integration—Frontend session context)
- **`docs/design/tokens.md`** — validate persona color tokens match mockup values (already extracted: purple #6a4fd0, blue #2a6fdb, terracotta #d97757, green #1f8a5b)

### Existing Patterns to Follow
- **Next.js App Router Server Components**: the shell is a presentational component; prefer Server Component (no `"use client"`) until interactivity is needed (per next-patterns)
- **CSS Modules per route**: `page.module.css` alongside `page.tsx` (already in use in `src/app/page.tsx`); the shell's own CSS should live in `PersonaShell.module.css` or be co-located with the component
- **Styled with inline CSS only** (per design README, decision §2): the mockups bind presentation via inline `style` attributes, not utility classes or external stylesheets; however, the DECISION that "templates bind CSS as well as data" suggests not copying the mockup's inline styles verbatim into the component, but rather importing design tokens and using a conscious CSS strategy (see risk register, Domain—CSS binding strategy)

### New Files to Create
- `apps/web/src/components/PersonaShell.tsx` — the shared header component exported from a single location, consumed by ARC-01, DEV-01, PMD-01, EMD-01 pages
- `apps/web/src/components/PersonaShell.module.css` — CSS Modules stylesheet for the component
- `apps/web/src/types/auth.ts` — TypeScript types for `CurrentUser` and `PersonaEnum` (mirrored from backend contracts for frontend type safety)
- `apps/web/src/lib/auth.ts` — utility functions to map backend persona enum to display strings ("architect" → "Architect", etc.), and format session data for display
- Tests: `apps/web/src/components/__tests__/PersonaShell.test.ts` (vitest)

### Shared Code at Risk
- **`docs/design/mockups/Architect|Developer|Product Manager|Engineering Manager Dashboard.html`** — ARC/DEV/PMD are identical in the persona-shell sections (differing only in the persona literals and tag colour); **EMD already diverges** (`proj.*` binding names, plus the "Switch program" control), resolved per C-4 as mockup drift with the switcher owned by EMD-01. Any future header change to one dashboard requires a coordinated change to all four, and re-opens whether the single-shell premise still holds.
- **`docs/requirements/auth.md` § session and persona-resolver** — both must remain stable across AUTH-01/02 and this story; any breaking change to the `CurrentUser` shape or `resolve()` signature ripples to all consuming pages (ARC-01..EMD-01)

### Pattern Decisions — resolved

- **Program-context ownership** — *decided, C-3*: the composing page hands the shell a fully-resolved program object; the shell owns no loading state for it and composes `avatarStyle` / `typeChip` from `docs/design/tokens.md` rather than receiving CSS as data. Consistent with story AC-2.
- **EMD subtitle case** — *closed*: the lowercase 'm' in "Engineering manager overview" is verified present in the decoded EMD markup. The mockup is the contract, so it ships verbatim as one of four per-persona literals — not a `Title(persona)` template, which would silently normalise it.

---

## Risk Register

| # | Dimension | Severity | Description | Mitigation |
|---|-----------|----------|-------------|-----------|
| 1 | Integration | HIGH | No frontend session/auth plumbing exists yet. The shell depends on `session` and `persona` props, but no parent component in `apps/web` has established a pattern for fetching the backend session contract or persona-resolver result. ARC-01/DEV-01/PMD-01/EMD-01 (the consumers) will define that pattern first; SHP-01 then consumes it. Tight coupling risk if the consuming dashboards establish divergent session-fetching patterns. | Establish a shared session/persona hook or context provider (e.g., `useSession()`, `SessionProvider`) in `apps/web/src/lib/` BEFORE any dashboard composes the shell. ARC-01 plan-implementation should include this seam. Document the exact prop shape the shell expects: `{ session: CurrentUser | null, persona: PersonaEnum | null, isLoading: bool, error?: Error }`. |
| 2 | Integration | HIGH | The persona-resolver is a backend-only service (`app.state.persona_resolver.resolve(role)` in FastAPI). The frontend has NO direct call site to it. The consuming dashboards (ARC-01..EMD-01) must arrange for the backend to resolve the persona and return it in the session response OR establish a dedicated `/api/me` endpoint that includes the resolved persona. This is a **seam design decision** the Backend Plan (BED-XX or AUTH-03) must clarify. | Before the shell is implemented in ARC-01, confirm: does `/api/me` or the session contract itself include the `persona` field? Or must each dashboard route call `persona_resolver.resolve(session.role)` and inject the result into the response? The shell's prop contract depends on this answer. |
| 3 | Domain | MED | The story decision log (line 44) notes that the "Architect" persona tag string is "inferred" by naming pattern, not sourced. The mockups confirm the tag is "Architect", but no requirement doc specifies that exact string. If the backend persona enum returns `"architect"` (lowercase), the shell must transform it. The four personas are: `architect` (to "Architect"), `developer` (to "Developer"), `product-manager` (to "Product Manager"), `engineering-manager` (to "Eng Manager"). Map these explicitly in `apps/web/src/lib/auth.ts::formatPersonaTag()`. | Document the transformation in the shell's component comments and in the lib function. Unit test all five enum values (including `cio`, which doesn't appear in the mockups and has no display string defined). Cover this in SHP-01 test mapping. |
| 4 | Domain | MED | Engineering Manager mockup (EMD) subtitle says "Engineering manager overview" (lowercase 'm'), while others are title case. This may be a mockup typo, or intentional. If intentional, the shell needs a conditional: `persona === "engineering-manager" ? "Engineering manager overview" : "${Title(persona)} overview"`. | Verified: the lowercase 'm' is present in the decoded EMD markup ("Engineering manager overview"), and the other three are title case. Per `CLAUDE.md` the mockup is the contract, so the **default is to implement it verbatim** (a per-persona subtitle literal, not a `Title(persona) + " overview"` template — the template would silently "fix" it). This is a confirm-the-default question, not a blocker. Document in the shell's Decision log. |
| 5 | Domain | MED | The mockups show the persona tag with persona-specific background colors (purple, blue, terracotta, green). The shell needs a color-map function: `getPersonaTagStyle(persona) → { color, background }`. These must match the mockup values exactly or the shell will not pass visual regression. | Extract and hard-code the color map from `docs/design/tokens.md` § persona colors. Test against the four extracted mockups post-implementation (or manually with a screenshot diff). |
| 6 | Domain | MED | The program context block binds `prog.avatarStyle` and `prog.typeChip` as presentation attributes. Per the design README decision §2, "the templates also bind presentation, not just data — … CSS in API responses." This contradicts the REST principle (data ≠ style). SHP-01 is presentational; it renders these values as-is. But if the consuming pages' backends start returning CSS as data, the style binding becomes a future risk. | Document this decision in the shell's component comments and in an ADR (e.g., "Design-system values from API responses — when they arrive, are they pre-formatted display values or CSS?"). No code change needed for MVP. Flag for architecture review. |
| 7 | Integration | **HIGH** | **Identity contract gap — no upstream supplies what the header displays.** The `persona-shell` contract (`docs/requirements/api.md`) declares `signed_in_user: { name, role }`. Its only identity upstream, the `session` contract (`docs/requirements/auth.md`), supplies `fields: { user_id: str, email: str, role: str, groups: [...] }` where `role` is "`<realm/client role claim>`" — the claim AUTH-02 maps to a persona. The mockups display a human display name ("Devon Rao"), a free-text job title ("Principal Architect"), and initials ("DR"). **None of the three is available in display form:** (a) `name` — `session` has `email` only; the story's Decision log assumes `email` fills it, but an email is not "Devon Rao", so the mockup and the assumption disagree and the mockup is authoritative per `CLAUDE.md`; (b) `role` — a job title is not the IdP role claim, and nothing verifies the Apexon realm's role claim carries job titles; (c) `initials` — absent from the story AND from the `persona-shell` field list entirely. The mockup cannot arbitrate the source because this block is the one region with no template bindings (Section 1, Binding status). | Resolve **before** `/arh-plan-requirements` writes the response shape — this determines whether AUTH-01's `session` contract must be extended (add Keycloak `name`/`given_name`/`family_name` + a job-title claim, requiring a realm mapper and an `OIDC_SCOPE`/claim change) or whether the header degrades to what `session` actually has (email as name, persona tag in place of job title, initials derived client-side from the email local-part). Extending `session` touches AUTH-01, already at `phase=review` — a contract change there is a cross-story amendment, not an SHP-01-local decision. Raised as Clarification 1. |
| 8 | Domain | LOW | Acceptance Criterion 4 (line 19 of story) specifies loading and error states: "shows a neutral loading state while pending and a generic error state on raise — never a blank or mismatched persona tag." The mockups do NOT show these states (only the happy path). The shell's implementation must include fallback UI for `isLoading` and `error` props. | Add loading and error state branches to the component. Define fallback UI in the test mapping and component comments. Example: loading → render skeleton or disabled state (no persona tag shown); error → render a fallback persona badge (e.g., "User" with neutral gray) + aria-live alert. Test coverage required per test mapping. |
| 9 | Performance | LOW | The shell renders within 200ms of props being available (NFR-001, per line 23 of story). The shell itself is presentational (no fetching), so the 200ms budget is the time from backend session-resolve to prop arrival in the component. This is owned by the consuming dashboard, not the shell. | Document the budget in the shell's prop interface comments. ARC-01/DEV-01/PMD-01/EMD-01 plans must allocate this time to their session/persona-fetching logic and parallel fetch strategies. No code change needed in SHP-01. |
| 10 | Security | LOW | The shell must not render persona-gated content (tag, subtitle) until both `session` and `persona` have resolved (line 24 of story: "avoids a flash of incorrect persona; displays the resolved persona tag, never the raw IdP role string"). If the consuming page renders the shell before persona resolves, a brief flash of old/wrong persona could occur. | The shell should gate the persona tag and subtitle rendering on `persona !== null`. Provide a loading skeleton or omit those elements until persona is ready. ARC-01..EMD-01 must pass both `session` and `persona` as props simultaneously, or implement a loading state. Test for this flash-of-wrong-persona scenario in the shell's test suite. |
| 11 | Compatibility | LOW | The four dashboards (ARC/DEV/PMD/EMD) have nearly identical headers, but EMD has a "Switch program" dropdown below the persona context. If future requirements add more persona-specific UI to the shell, a new conditional branch could emerge. | Treat the shell as composition-ready: it renders the generic persona tag, subtitle, and program context. EMD-specific UI (the "Switch program" dropdown) is NOT part of the shell — it's part of the EMD dashboard page layout, rendered AFTER the shell. This boundary must be clear in the component API and comments. Verify in ARC-01/DEV-01/PMD-01/EMD-01 planning that the dropdown is a sibling to the shell, not a child. |

---

## Score + Verdict

### Rubric

| Dimension       | Weight | Score | Reasoning |
|-----------------|--------|-------|-----------|
| **Integration** | 25     | 65    | Upstream contracts (AUTH-01, AUTH-02) are complete and ready. However, the frontend has NO session/auth plumbing yet, and the seam between the shell and the consuming dashboards (where session/persona are fetched) is undefined. ARC-01 plan-implementation will need to establish that pattern first; SHP-01 then consumes it as a consumer, not a provider. The risk is that ARC-01/DEV-01/PMD-01/EMD-01 establish divergent session patterns, fragmenting the codebase. This is mitigable via clear prop contracts and shared hooks (before implementation), but represents measurable integration friction. |
| **Compatibility** | 20     | 80    | The mockups show the shell is nearly identical across three of four dashboards (ARC/DEV/PMD differ only in colors); EMD is a minor variant with an extra control. Backward-compat risk is low (this is a new component, no legacy code to support). Forward-compat risk is low if the EMD variant is explicitly a page-level sibling, not a shell extension. |
| **Domain**       | 20     | 70    | The story's assumptions are documented (Decision log lines 42-47) and mostly validated against mockups. However, three assumptions are NOT fully answered: (1) The "Architect" tag string is inferred, not sourced — mockups confirm it, but no enum-to-string mapping is specified in a requirement. (2) The EMD subtitle's lowercase 'm' may be a typo. (3) The program context's CSS-binding pattern (avatarStyle, typeChip from API) is a future decision deferred. These are manageable with disciplined mapping functions and explicit test coverage, but represent spec gaps. |
| **Performance** | 15     | 85    | The shell's own 200ms budget (NFR-001) is a rendering constraint, not a fetching constraint. The shell is purely presentational (no I/O). The budget is owned by the composing pages' session/persona-fetching logic, not the shell. Estimated implementation (a TSX component with CSS Modules) will render in <10ms. No measured perf risk. |
| **Dependency**  | 20     | 80    | AUTH-01 and AUTH-02 are both complete (research_verdict GO-WITH-CONDITIONS, implemented). The downstream dashboards (ARC-01..EMD-01) are validated stories but not yet researched; they depend on SHP-01 to exist and be spec'd. SHP-01 is a BLOCKING upstream for their implementation, but not a risk — its research is complete, and it's a straightforward component. Estimated dependency flow: SHP-01 research → plan-requirements → plan-implementation → implement. Timeline is clear. |

### Weighted Total

```
(65 * 0.25) + (80 * 0.20) + (70 * 0.20) + (85 * 0.15) + (80 * 0.20)
= 16.25 + 16.00 + 14.00 + 12.75 + 16.00
= 75.00 / 100
```

**Total: 75/100 → GO-WITH-CONDITIONS**

---

## Conditions for Proceeding

The plan-requirements phase MUST address:

1. **AUTH-01 `session` contract amendment (decided, not yet done)**: Resolved per C-1 — extend `session` with display-name and job-title claims. The *decision* is closed; the *work* is not, and it lands outside SHP-01: it changes the `session` contract in `docs/requirements/auth.md`, the Keycloak realm mappers, `OIDC_SCOPE`, and AUTH-01's own artefacts while AUTH-01 sits at `phase=review`. `/arh-plan-requirements SHP-01` must not write a response shape that assumes the extended contract until that amendment is actually raised against AUTH-01. This is the one remaining sequencing blocker — see also condition 2.

2. **Frontend session context seam**: Define the exact shape of the session/persona props the shell expects, and establish where those are fetched/resolved in the consuming pages. Do this BEFORE the shell's plan-implementation, or coordinate it as a parallel task.

3. **Persona enum-to-string mapping** — *decided, C-2*: hardcode the four transformations in `apps/web/src/lib/` with unit tests. `cio` is an invariant violation, not a fifth display case: fail loudly, never render a fabricated or blank tag.

4. **EMD subtitle variance** — *closed*: the lowercase 'm' is verified present in the decoded EMD markup. Per `CLAUDE.md` the mockup is the contract, so implement four per-persona subtitle literals verbatim. Do **not** use a `Title(persona) + " overview"` template — it would silently "fix" the mockup.

5. **CSS binding strategy** — *decided, C-3*: the shell composes `avatarStyle` / `typeChip` from `docs/design/tokens.md`; API responses carry data only. This is a deliberate divergence from the mockup's literal style bindings and answers `docs/design/README.md` decision 2 for the whole project, so it is worth an ADR rather than a code comment.

6. **Loading/error state UI**: Define the fallback UI for isLoading and error scenarios, and include in test coverage.

7. **Component API clarity** — *constrained by C-1/C-4*: one prop interface, one prop name (`program`, not `prog`/`proj`), no persona conditionals, and no switcher slot (EMD-01 renders that as a sibling). The `signed_in_user` half cannot be finalised until the C-1 amendment lands.

---

## Synthesis

SHP-01 is a **straightforward presentational component** that renders a fixed header UI consuming authenticated session data and persona-resolution output from upstream backends (AUTH-01, AUTH-02). Both upstreams are complete and ready. The frontend codebase is bare-bones scaffold with no session/auth plumbing yet; this shell will be the first frontend component to consume backend contracts, creating an integration seam that MUST be coordinated with ARC-01/DEV-01/PMD-01/EMD-01's own session-fetching logic. ARC/DEV/PMD are one screen with a swapped label (as `docs/design/README.md` itself states); EMD is a genuine variant — it renames the program binding `prog.*` → `proj.*` and adds a "Switch program" control inside the header region, so the "one shell, four pages" premise holds for three pages and needs an explicit decision for the fourth. Of the story's four documented assumptions, the mockups **settle two** (the "Architect" tag string and the four subtitle literals are present verbatim, so those stop being inferences) and **cannot settle the most consequential one**: the signed-in-identity block is the only region of the mockup with no template bindings, and the display name / job title / initials it shows have no source in any current contract — `session` carries `email` and an IdP role claim, not "Devon Rao" and "Principal Architect". That is a contract gap, not a documentation gap, and it is the one item here that cannot be closed by comments and unit tests. The primary risk is integration friction if the consuming dashboards establish divergent session patterns — mitigated by establishing a shared session hook / context provider before any dashboard implements the shell. Score of 75 stands: the component itself is genuinely simple and both upstreams are built, but three HIGH integration risks (no frontend session plumbing, no frontend persona-resolver call site, and the identity contract gap) all resolve at the same seam — what the frontend is actually handed. Conditions 1 and 2 close that seam before implementation. All four clarifications were resolved by the user on 2026-09-03 (see § Clarifications) — the score and verdict are unchanged, since the decisions settle *what* to build without removing the two unowned-work risks: the AUTH-01 contract amendment and the missing `apps/web` session seam.

---

## Resolved decisions (C-1 – C-4)

_Retitled from `## Clarifications` by the `/arh-plan-requirements` Phase 0 gate: the
`phase-preconditions` clarification gate treats **any** non-empty `## Clarifications`
section as an unresolved open question, so a section holding answers would have blocked
the phase on a naming technicality. Content is unchanged — these are settled decisions,
not pending questions, and the heading now says so. Zero clarification markers remain
anywhere in this document._

**All 4 resolved 2026-09-03 by the user during `/arh-research`.** No open markers remain; the
`phase-preconditions` clarification gate is clear for `/arh-plan-requirements`.

### C-1 — Signed-in identity source → **extend AUTH-01's `session` contract**

The header's display name, job title and initials come from new IdP claims, not from `email`.
This is the mockup-faithful option and was chosen deliberately over degrading the header.

Work it implies:

- Keycloak: a mapper for a display-name claim (`name`, or `given_name`/`family_name`) and one for
  a job-title claim; a new client scope + `OIDC_SCOPE` entry if the claims are not already on the
  realm's default scopes.
- `session` contract (`docs/requirements/auth.md`): `fields` grows from
  `{user_id, email, role, groups}` to include the display name and job title.
- `persona-shell` contract (`docs/requirements/api.md`): `signed_in_user: { name, role }` becomes
  name + job title; **initials are derived in the shell** from the display name ("Devon Rao" → "DR"),
  not carried as a third claim.
- **Cross-story amendment**: this changes AUTH-01, which is at `phase=review`. It is not an
  SHP-01-local change and must be raised against AUTH-01 before SHP-01 is planned. See Conditions § 1.

Supersedes the story's Decision-log assumption that `session.email` fills the name field
(`docs/stories/SHP-01.md`, 2026-08-26 entry) — that assumption is now decided against.

### C-2 — Persona enum → display string → **hardcoded in `apps/web/src/lib/`**

A `formatPersonaTag()` helper with unit tests per enum value. These are UI copy: they change with
design, not with ops, and the shell is the only consumer — so no config surface. `cio` is **not** a
display case: the CIO has its own dashboard under the OVW epic and never composes this shell, so a
`cio` value reaching it is an invariant violation. The shell must fail loudly rather than fabricate
a tag — never render a guessed or blank persona tag (consistent with story AC4).

### C-3 — `program_context` → **page resolves the data, shell composes the CSS**

The composing dashboard hands the shell a fully-resolved program object; the shell derives
`avatarStyle` / `typeChip` itself from `docs/design/tokens.md`. The shell owns no loading state for
program context, staying presentational as the story specifies.

This **declines** the precedent the mockup's literal style bindings would set (`{{ prog.avatarStyle }}`,
`{{ prog.typeChip }}` as API-supplied strings) — the divergence is deliberate, and it answers the
open question `docs/design/README.md` decision 2 raises: styling stays in the frontend, and API
responses carry data only. Risk 6 is closed by this decision, not deferred to an ADR.

### C-4 — EMD divergence → **one prop name, switcher owned by EMD-01**

A single prop name (`program`) across all four pages; the `prog.*` / `proj.*` split in the mockups
is treated as mockup drift, not a real difference. EMD-01 renders the "Switch program" dropdown as
a **sibling after the shell**, not inside it. The shell carries no persona conditionals and stays
one component across all four dashboards. Risk 11's boundary question is settled this way.
