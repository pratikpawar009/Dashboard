# Feature: SHP-01 — Persona header/context shell

## Problem

Four persona dashboards (Architect, Developer, Product Manager, Engineering Manager) each need identical orientation UI — who's signed in, which persona view they're in, which program is in scope — and today none of it exists: no shared component, no frontend session/auth plumbing at all, and the one upstream contract the header depends on (`session`) doesn't yet carry a human-readable identity. Without a single shell, ARC-01/DEV-01/PMD-01/EMD-01 would each re-implement (and likely diverge on) the same header.

## Outcome

A single shell — consumed identically by ARC-01, DEV-01, PMD-01, EMD-01 — renders the product header, signed-in identity, persona tag, persona-specific subtitle, and program context from props alone, with no data fetching and no persona conditionals of its own. Ships in two phases: persona tag / subtitle / program context are wired from day one; the signed-in identity block activates once AUTH-01's session-contract amendment lands (see Rollout plan).

## Constraints

- AUTH-01's `session` contract must be amended (display-name + job-title claims) before the identity block can show real values; AUTH-01 is at `phase=review` — this is a cross-story amendment, not an SHP-01-local change (Addressing Research Conditions, C-1).
- The frontend session/persona prop seam (what the shell receives, and where it's fetched) must be established by the consuming dashboards before or alongside SHP-01's implementation — SHP-01 defines the prop interface, not the fetch (condition 2).
- The mockups (`docs/design/schema.json` → ARC/DEV/PMD/EMD) are the UI contract for this shell (`CLAUDE.md`) and are desktop-only, no breakpoints (`docs/design/tokens.md` § Responsive) — no mobile layout exists yet.
- One component, one prop interface (`program`), zero persona conditionals, across all four consuming pages (C-4).
- The shell makes no backend calls of its own — purely presentational (story Dependencies).

## Solution sketch

A presentational shell composed of three sub-regions — a signed-in identity bar, a persona-context header (tag + subtitle), and a program-context block — accepting a `session`-derived identity, a resolved `persona` enum, and a page-supplied `program` object as props, with no fetching and no persona-specific branching in its own code. Persona-to-string and persona-to-color mappings are hardcoded and unit-tested; the identity block degrades to a neutral fallback until AUTH-01 supplies the display-name/job-title claims it needs.

## Addressing Research Conditions

Research verdict: GO-WITH-CONDITIONS, score 75/100, 7 numbered conditions from `docs/research/SHP-01.md` § "Conditions for Proceeding":

- **C-1: AUTH-01 `session` contract amendment (decided, not yet done)** — this PRD specifies the `signedInUser` prop shape (FR-1) but does **not** assume the extended contract ships: the identity block degrades to FR-5's neutral state whenever `signedInUser` is absent, which is exactly the pre-amendment condition (Rollout plan) — no feature flag, per `.claude/rules/reusability-baseline.md`. Flagged as the single biggest risk in Constraints and Rollout plan.
- **C-2: Frontend session context seam** — FR-1 and FR-4 define the exact prop shapes (`signedInUser`, `persona`, `program`) the shell expects; fetching/resolving them is explicitly Out of Scope, owned by ARC-01/DEV-01/PMD-01/EMD-01.
- **C-3: Persona enum-to-string mapping** — FR-2: hardcoded `formatPersonaTag()` map in `apps/web/src/lib/`, one unit test per of the 5 possible resolver outputs; `cio` throws rather than rendering a fabricated or blank tag.
- **C-4: EMD subtitle variance** — closed by the mockups; AC3 (story) plus Screen inventory carry the four literal subtitles verbatim, including the lowercase 'm' in "Engineering manager overview" — never a `Title(persona)` template.
- **C-5: CSS binding strategy** — FR-4: `program` prop carries data only (icon, name, type, description); the shell composes `avatarStyle` and the type-chip color itself from `docs/design/tokens.md`. Declines the mockups' literal style-binding precedent by design.
- **C-6: Loading/error state UI** — FR-5 defines the concrete fallback markup for both states (previously undefined by story or mockups), with test coverage required in Scope.
- **C-7: Component API clarity** — FR-4: one prop interface, one prop name (`program`, not `prog`/`proj`), no persona conditionals; the "Switch program" dropdown is explicitly Out of Scope, rendered by EMD-01 as a sibling after the shell.

## Scope

**In:**
- Shared shell rendering three sub-regions — signed-in identity bar, persona-context header (tag + subtitle), program-context block — as one composed unit per story AC1, consumed identically by ARC-01/DEV-01/PMD-01/EMD-01.
- `formatPersonaTag()` persona-enum-to-display-string map, unit-tested per enum value, `apps/web/src/lib/`.
- Persona-to-color map for the tag and the initials-avatar background, sourced from `docs/design/tokens.md`.
- Initials derivation from `signedInUser.name` (FR-3).
- `program` prop consumption plus client-side `avatarStyle` / type-chip color composition (C-3/C-4).
- Loading and error fallback states (FR-5).
- Unit tests: `PersonaHeader.tsx`, `ProgramContext.tsx`, `PersonaDashboardShell.tsx` (story Test mapping).

**Out:**
- Fetching or resolving `session` / calling the persona-resolver — owned by the consuming dashboard pages (condition 2).
- The AUTH-01 session-contract amendment itself (Keycloak mappers, `OIDC_SCOPE`, `docs/requirements/auth.md` edits) — cross-story work tracked against AUTH-01, not SHP-01.
- EMD-01's "Switch program" dropdown — a sibling component rendered after the shell, not part of it (C-4).
- Resolving/fetching the `program` object — supplied fully-resolved by the composing page (C-3).
- Mobile/responsive layout — mockups are desktop-only; no mobile design exists yet for this shell.
- Telemetry/observability — the shell emits none of its own (story NFR); session/persona logging is owned by AUTH-01/AUTH-02.
- Updating `docs/requirements/auth.md` / `docs/requirements/api.md` contract docs — happens when the AUTH-01 amendment lands, not in this PRD.

## Functional requirements

FRs trace 1:1 to story ACs; see `docs/stories/SHP-01.md` for canonical wording. New impl constraints introduced below (when any):

**SHP-01-FR-1** — Signed-in identity prop shape, pending AUTH-01 amendment *(extends AC1 with: exact prop shape and its unlanded dependency)*

The shell accepts `signedInUser: { name: string; jobTitle: string } | undefined`. Both fields are sourced from claims AUTH-01 has not yet added to the `session` contract (C-1); until that cross-story amendment lands (AUTH-01 is at `phase=review`), the composing page cannot supply real values and the shell renders its neutral fallback (FR-5), never a placeholder name or blank field. The `persona-shell` contract's current `signed_in_user: { name, role }` is provisionally renamed `{ name, jobTitle }` here — logged as an assumption in `docs/stories/SHP-01.md` § Decision log, since `role` already names the raw IdP claim, distinct from job title and from the persona tag (research Risk 7) — finalized only when the AUTH-01 contract change lands. Initials are never a prop (see FR-3).

**SHP-01-FR-2** — Persona tag map and `cio` invariant *(extends AC1 with: the exact map and fail-loud behavior)*

`formatPersonaTag(persona)` maps `architect → "Architect"`, `developer → "Developer"`, `product-manager → "Product Manager"`, `engineering-manager → "Eng Manager"` — sourced from the decoded mockups (`docs/research/SHP-01.md` § Design Mockup Analysis). `cio`, or any value outside the four, throws rather than rendering a fabricated or blank tag: the shell never composes for the CIO dashboard (OVW epic), so a `cio` value reaching it is a caller bug. Each of the 5 possible resolver outputs (4 valid personas + `cio`) has a dedicated unit test.

**SHP-01-FR-3** — Initials derivation *(extends AC1/mockup: initials appear in the mockup's identity bar but are in neither the story nor the current `persona-shell` field list — research Risk 1a)*

Initials render inside a 34×34px persona-coloured circle (persona tag color, `docs/design/tokens.md`). Derived from `signedInUser.name`: uppercase first letter of each of the first two space-separated tokens (`"Devon Rao"` → `"DR"`); a single-token name yields that one letter only, no doubling — logged as an assumption in `docs/stories/SHP-01.md` § Decision log (neither the story nor the mockups' static markup covers the single-token case). Never rendered until `signedInUser` resolves (FR-5's loading gate).

**SHP-01-FR-4** — Single `program` prop; shell composes CSS, API/prop supplies data only *(extends AC2 with: prop-name unification per C-4 and the CSS-composition rule per C-3)*

All four consuming pages pass the same prop `program: { icon: string; name: string; type: string; description: string }` — data only, no `avatarStyle` / type-chip CSS strings, despite the mockups binding those as template variables. The shell derives `avatarStyle` and the type-chip color from `program.type` via a lookup table sourced from `docs/design/tokens.md`, never from the prop. The mockups' `prog.*` (ARC/DEV/PMD) vs `proj.*` (EMD) split is mockup drift (C-4); the shell recognizes one prop name across all four pages. The shell owns no loading state for `program` (composing page resolves it before render, per C-3); an absent/undefined `program` is a caller error, not a shell-rendered empty state.

**SHP-01-FR-5** — Loading and error fallback UI *(extends AC4: neither the story nor the mockups specify concrete fallback markup)*

**Loading** (session or persona not yet resolved): render the static product header only; suppress the signed-in-identity bar, persona tag, subtitle, and program context entirely — no skeleton, no partial or mismatched persona — until both `session` and the resolved `persona` are available, per the story's flash-prevention NFR. **Error** (persona-resolver raised, i.e. `PersonaNotFoundError`, or a `cio` value reaches the shell per FR-2): render a neutral gray badge reading "Persona unavailable" in place of the persona tag, keep the header subtitle-less, and announce failure via a visually-hidden `aria-live="assertive"` region ("Unable to load your dashboard view.") — logged as an assumption in `docs/stories/SHP-01.md` § Decision log (AC4 specifies the requirement, not the copy/markup).

## Non-functional requirements

- **SHP-01-NFR-1** Performance: shell render ≤200ms p95 from props (`session` + persona-resolver output) being available — sourced from the story NFR (there itself logged as an assumption; no source budget exists for this presentational component). The shell performs no I/O; this budget is render time only — the upstream fetch/resolve time is owned by the composing pages (ARC-01/DEV-01/PMD-01/EMD-01), not this component.
- **SHP-01-NFR-2** Security: Per `.claude/rules/security-baseline.md`: applies to this component's handling of identity data (no new endpoints are introduced). Feature-specific: never render persona-gated content (tag, subtitle) until both `session` and `persona` have resolved (avoids a flash of the wrong persona); never render the raw IdP role string; a `cio` value or a resolver raise fails loudly per FR-2/FR-5, never silently defaulting; `signedInUser.name`/`jobTitle` (PII) are rendered only, never logged or forwarded to analytics.
- **SHP-01-NFR-3** Accessibility: Per `.claude/rules/accessibility-baseline.md`: applies to all new UI surfaces in this story (signed-in identity bar, persona-context header, program-context block). Story NFR softens the baseline to "WCAG AA, where feasible" (per story NFR-008) — carried here verbatim rather than silently tightened or loosened. Feature-specific: the four persona tag/background color pairs (`docs/design/tokens.md`) must be verified ≥4.5:1 text contrast as part of design QA in `DESIGN.md`; the error-state announcement (FR-5) uses `aria-live="assertive"`.
- **SHP-01-NFR-4** Observability: N/A — this presentational shell emits no telemetry of its own; session/persona-resolution logging (`persona_mapping_loaded`, etc.) is owned by the AUTH-01/AUTH-02 contracts it consumes (story NFR).

## Screen inventory

Scoped to the shell's own regions across the four persona dashboards (ARC/DEV/PMD/EMD epics in `docs/design/schema.json`), not the full dashboards those epics own.

| Screen | Route | Render | Primary purpose | States | Story ACs covered |
|---|---|---|---|---|---|
| Signed-in identity bar | — (embedded above the `<!-- HEADER -->` region, within ARC-01/DEV-01/PMD-01/EMD-01 routes) | server (no client interactivity in MVP) | Product brand ("AgentRise Harness" / "AI SDLC Governance") + signed-in user's name, job title, initials avatar | Loading (suppressed) / Populated / Error (neutral badge) | AC1, AC4 |
| Persona-context header | — (embedded `<header>` region, same 4 routes) | server (no client interactivity in MVP) | Persona tag + persona-specific subtitle literal | Loading (suppressed) / Populated / Error (neutral badge) | AC1, AC3, AC4 |
| Program-context block | — (embedded inside the persona-context header, same 4 routes) | server (no client interactivity in MVP) | Program icon, name, type chip, description composed from the page-supplied `program` prop | Populated only — no shell-owned loading/empty state, per C-3 | AC2 |

The "Switch program" dropdown (EMD mockup only) is explicitly out of this inventory — it is a sibling control owned by EMD-01, rendered after the shell (C-4), not one of the shell's own regions.

## Visual spec

Pending — `ux-agent` will write [DESIGN.md](./DESIGN.md) during `/arh-plan-requirements` design phase.

## Rollout plan

- **Strategy**: phased. Phase 1 ships persona tag, subtitle, and program context (C-2/C-3/C-4 are all fully resolved, nothing blocks these). Phase 2 activates the signed-in identity block once AUTH-01's session-contract amendment lands.
- **No feature flag** — `.claude/rules/reusability-baseline.md` forbids config switches that fork the call graph, and one is not needed here: the phase boundary is already expressed by data presence. `signedInUser` is typed `| undefined` (FR-1), so before the AUTH-01 amendment lands the composing pages simply cannot supply it, `undefined` flows through, and FR-5's neutral fallback renders. After the amendment they pass real values and the identity bar renders. **One code path, switched by whether the data exists** — the same branch AC4 already requires for unresolved session data, not a second mechanism layered on top. A flag here would have duplicated FR-5 and forked the render path for a condition the type system already models.
- **Backout plan**: stop passing `signedInUser` from the composing pages — the shell falls back to the FR-5 neutral identity state with no shell change and no redeploy of the shell itself. Full component backout is removing the shell import from the four consuming pages — presentational-only, no schema or data migration involved.
- **Success signal**: Phase 1 — all four persona dashboards render the shell with persona tag/subtitle/program-context matching the mockups, zero visual regressions against `DESIGN.md`. Phase 2 — once the composing pages begin supplying `signedInUser`, the identity bar shows non-empty `name`/`jobTitle` and the FR-5 identity fallback stops appearing in production renders within 24h.

## Documentation requirements

- **README updates**: none — this introduces a shared frontend component, not a new route or service; no root `README.md` API-table change applies.
- **Runbook**: none.
- **API reference**: none — no new API route. The `session` and `persona-shell` contract docs (`docs/requirements/auth.md`, `docs/requirements/api.md`) are updated when the AUTH-01 amendment lands (Out of Scope here).
- **Inline code comments**: `apps/web/src/components/PersonaHeader.tsx`, `ProgramContext.tsx`, `PersonaDashboardShell.tsx` — TSDoc documenting the prop contract, the pending-AUTH-01-amendment caveat on `signedInUser` (FR-1), the persona-enum-to-tag map and `cio` fail-loud behavior (FR-2), and the loading/error fallback states (FR-5). `apps/web/src/lib/formatPersonaTag.ts` (or equivalent) — document the four literal tag/subtitle strings sourced from the mockups, with an explicit comment against templating them.
- **Examples / how-to**: none.

## Open questions

<!-- None open. All directional ambiguities were resolved in research (C-1-C-4,             -->
<!-- docs/research/SHP-01.md § Resolved decisions). The one unresolved *dependency* -         -->
<!-- AUTH-01's session-contract amendment - is tracked as a Constraint and as condition 1     -->
<!-- of § Addressing Research Conditions, plus a phased-rollout gate, not as an open          -->
<!-- question against this PRD.                                                              -->
<!--                                                                                          -->
<!-- Three implementation-level specifics with no prior source (the signedInUser field        -->
<!-- rename, single-token initials, the error-fallback copy) were resolved inline as          -->
<!-- logged assumptions - see docs/stories/SHP-01.md § Decision log, 2026-09-03 entries.      -->
<!-- needs_clarification_count: 0.                                                            -->
<!--                                                                                          -->
<!-- Kept as a comment deliberately, matching docs/features/BED-04/REQUIREMENTS.md: the      -->
<!-- phase-preconditions clarification gate treats ANY non-blank, non-comment line in this   -->
<!-- section as an unresolved open question and aborts the next phase. Prose saying "None"    -->
<!-- trips it.                                                                                -->

## Approvals

**APPROVED** — Pratik Pawar (pratik.pawar@apexon.com), 2026-09-03, via the `/arh-plan-requirements` Product Gate.

Two checklist items were failing at approval and were **accepted as recorded gaps**, not silently passed:

| Item | Status at approval | Why accepted |
|---|---|---|
| Test-case coverage audit shows zero uncovered ids | **GAP — `SHP-01-FR-1`, `SHP-01-FR-3`** | A ≤4 test-case cap was an explicit instruction for this run. Both uncovered FRs depend on the AUTH-01 `session` contract amendment (C-1), which is decided but has not landed — a test pinned to field names that amendment may rename has negative value. `SHP-01-TC-02` covers the stable half of FR-1 (the `undefined` fallback path). Revisit both once the amendment lands. |
| Designer approves UI specifications via `DESIGN.md` | **NOT PRODUCED** | `ux-agent` is not installed in `.claude/agents/`, so Phase 2's design branch had no worker. `design` stays `pending` — deliberately **not** `n/a`, since this story renders UI and the ARC/DEV/PMD/EMD mockups govern it. `## Screen inventory` is written and ready for a designer or a future ux-agent; `## Visual spec` remains the Pending stub. |

Carrying into `/arh-plan-implementation`: FR-1's prop shape is provisional until the AUTH-01 amendment lands (Constraints, condition 1), and no story yet owns the `apps/web` session seam (condition 2).
