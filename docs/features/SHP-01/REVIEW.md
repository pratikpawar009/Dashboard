# Code Review — feature/SHP-01 (working tree, GATE MODE round 1/3)

- Date: 2026-09-03T00:00:00Z
- Mode: current (uncommitted working tree, `/arh-implement` Validate ∥ Review gate)
- Files reviewed: 15 (`file_plan` F-01..F-15) + 2 planning-phase doc edits (`docs/requirements/api.md`, `docs/stories/SHP-01.md`, both accounted for outside `file_plan` per PLAN.md §4/§9 — see Scope discipline)
- Verdict: **PASS WITH WARNINGS**

## Executive summary

A pure, prop-driven persona shell (`types/`, `lib/`, `components/`) built with no in-repo consumer, matching `file_plan` exactly — zero scope-creep. `formatPersonaTag`'s fail-loud invariant, D-03's single-persona-prop design, and D-05's identity neutral fallback are all implemented as decided and are correctly tested. One real mockup-fidelity defect: the program-context avatar box renders a caller-supplied `program.icon` field verbatim, but all four decoded mockups compute that box's content from `program.type` (`tMap[ptype].ab`) — there is no independent "icon" concept anywhere in the design system. `docs/design/tokens.md`'s own newly-added "Avatar abbreviation" column is dead — nothing in the diff reads it. One D-06 letter-violation (neutral-fallback hexes hardcoded in TS instead of the CSS Module) duplicates values already declared in `PersonaHeader.module.css`. AF-01 through AF-07 were all reviewed against their stated resolutions and are handled correctly or are legitimately deferred to human triage; none re-raised here.

🟢 Fail-loud/fail-soft split (persona vs. program.type), D-02 color-agreement guarantee, D-05 neutral identity fallback, scope discipline, test quality (TC-01/02/03/04 all assert real behavior, not vacuous)
⚠️ D-06 hardcoded neutral hexes outside the CSS Module; untested `avatarColorStyle()` catch branch; shared object reference in `getProgramStyle()`
🛑 `program.icon`/avatar-box mockup-fidelity mismatch — corrupts the `persona-shell` contract that ARC-01/DEV-01/PMD-01/EMD-01 will bind against

## Judgment calls (requested by the gate)

- **C-7 ("no persona conditionals")**: holds. `avatarColorStyle()`'s `try`/`catch` (`PersonaDashboardShell.tsx:131-140`) branches on *validity*, not on any specific persona value, and treats all four personas identically — it is the same class of check `PersonaHeader` already performs, not a per-persona special case. `tasks.json` T-10's note ("No persona-conditional branching beyond isLoading exists in this file") is imprecise — this second branch does exist in the file — but it does not violate what C-7 is actually guarding against.
- **D-02 survives the neutral fallback**: yes. `PersonaHeader`'s `.pillNeutral` (`#5b6472`/`#e4e7ec`) and `avatarColorStyle()`'s catch branch (`#5b6472`/`#e4e7ec`) are byte-identical, so the tag and avatar still can't disagree in the error case. See Finding F-2 for why this agreement is fragile (duplicated literals, no shared source).
- **AF-03 interpretation**: agree with mirroring `PersonaHeader`'s neutral degradation — it's the only choice consistent with D-02/D-03 without inventing a fourth state. Confirm at human review as instructed; the only gap left is that no test exercises this exact branch (Finding F-4).
- **Fail-loud (`formatPersonaTag` throws) vs. fail-soft (`getProgramStyle` falls back to Migration)**: coherent, not an inconsistency. `persona` is a shell-owned invariant (AUTH-02 contract); `program.type` is caller-resolved external data mirroring the mockup's own `tMap[...] || tMap['Migration']`. Both sides document the other's opposite behavior inline — no fix needed.
- **`getProgramStyle()` shared object reference**: safe today (React only reads `style`, never mutates it; no code in this diff mutates the returned object). Flagged at LOW (Finding F-3) as a latent footgun, not a defect.

## Findings summary

| Severity | Count | Category distribution |
|----------|-------|------------------------|
| CRITICAL | 0 | — |
| HIGH | 1 | design-patterns (1) |
| MEDIUM | 1 | adr-violation (1) |
| LOW | 2 | design-patterns (1), testability (1) |

## Detailed findings

### HIGH

#### F-1 — design-patterns: program-context avatar renders a fabricated `icon` field instead of the mockup's type-derived abbreviation

- Category: design-patterns
- Path: `apps/web/src/components/ProgramContext.tsx:23,29`; `apps/web/src/lib/programStyle.ts:16-31`; `docs/requirements/api.md:70`; `docs/design/tokens.md:57-62`
- Source: `CLAUDE.md` § Design system ("API/backend stories supply exactly what the mockup's bindings consume... The mockup, not the PRD prose, settles response shape"); ground truth verified directly against the decoded mockups (`arc.pretty.html:864`, `dev.pretty.html:864`, `pmd.pretty.html:864`, `emd.pretty.html:739-765`)
- Description: In all four decoded mockups, the avatar box's content (`{{ prog.avatar }}` / `{{ proj.avatar }}`) is **computed from `program.type`** — `avatar: t.ab` in `emd.pretty.html:765` (`tMap[ptype].ab`, one of `M`/`G`/`B`/`MT`), and the literal `'M'` in arc/dev/pmd because their fixture data is always `ptype: 'Migration'`. There is no field anywhere in the mockup source, `docs/design/schema.json`, or any other contract (`program_id, label, href, dotStyle` for the switcher list) that supplies an independent per-program icon/emoji. `docs/design/tokens.md`'s own new "Program type colors" table already carries this exact value in its "Avatar abbreviation" column (`M`/`G`/`B`/`MT`) — added by this same diff (D-04) — but `getProgramStyle()` never returns it, and `ProgramContext.tsx` instead renders whatever the caller passes as `program.icon` verbatim (test fixtures use `"🏗️"`/`"🚀"`, values with no mockup basis at all). The `icon` field name predates this diff (`docs/stories/SHP-01.md:20,34`, pre-existing `api.md` stub), and `docs/research/SHP-01.md:58` conflated "icon/avatar" without checking that `prog.avatar` is derived, not supplied — but this diff is what re-asserts the shape in `docs/requirements/api.md` (the contract ARC-01/DEV-01/PMD-01/EMD-01 will build against) and is what ships the incorrect render + two passing unit tests (`ProgramContext.test.tsx`) locking the wrong behavior in.
- Suggested fix: Have `getProgramStyle(type)` also return the type's abbreviation (a third key, e.g. `avatarLabel: string`, sourced from `tokens.md`'s already-correct "Avatar abbreviation" column) and have `ProgramContext` render that instead of `program.icon`. Drop `icon` from `ProgramContextData`/`docs/requirements/api.md#persona-shell`'s `program` prop (nothing upstream produces it, and it duplicates information already derivable from `type`), or explicitly re-scope it as a future extension point if a real per-program icon source is anticipated later — but say so, don't leave it silently wrong. Update `ProgramContext.test.tsx` accordingly.

### MEDIUM

#### F-2 — adr-violation: neutral-fallback hexes hardcoded in TS instead of the CSS Module, per D-06's own rule

- Category: adr-violation
- Path: `apps/web/src/components/PersonaDashboardShell.tsx:138` (also documented at `:127`)
- Source: `DECISIONS.md` D-06 ("every static value — padding, font size, weight, radius, border **and neutral-ramp colors**... is a literal rule in the component's own `.module.css`... Only the data-driven color pair crosses the boundary")
- Description: `avatarColorStyle()`'s catch branch returns a fixed, non-data-driven pair (`#5b6472`/`#e4e7ec` — explicitly "neutral-ramp colors" per D-05's own description of `#e4e7ec`). D-06 says exactly this class of value belongs in the CSS Module, not in a `CSSProperties` object crossing a component boundary — and `PersonaHeader`'s own analogous neutral case (`PersonaHeader.module.css:28-30`, `.pillNeutral`) does it that way, via `className`, not `style`. The two now hold the same hex pair as independent literals in two files; a future edit to one (e.g. a border-ramp token change in `tokens.md`) has no compiler or lint signal forcing the other to follow, silently reopening the D-02 color-agreement gap Judgment call #2 above currently closes only by coincidence.
- Suggested fix: Add a static `.avatarNeutralColor { color: #5b6472; background: #e4e7ec; }` rule to `PersonaDashboardShell.module.css` (matching `.pillNeutral`'s values) and apply it via `className` in the catch-branch render, reserving `avatarColorStyle()`'s `CSSProperties` return only for the genuinely data-driven success case.

### LOW

#### F-3 — design-patterns: `getProgramStyle()` returns one shared object reference for both `avatarStyle` and `typeChip`

- Category: design-patterns
- Path: `apps/web/src/lib/programStyle.ts:27-28`
- Source: `.claude/rules/reusability-baseline.md` (module clarity / no surprising shared state)
- Description: `const style = {...}; return { avatarStyle: style, typeChip: style }` — both keys alias the same object. Correct today (the mockup genuinely uses an identical `{color, background}` pair for both, and nothing in this diff mutates the returned object), but any future caller that does `Object.assign(result.avatarStyle, {...})` or similar in-place edit for one consumer would silently corrupt the other.
- Suggested fix: Return two separate object literals with identical values (or `Object.freeze` the shared one) to remove the coupling at negligible cost.

#### F-4 — testability: `avatarColorStyle()`'s catch branch (AF-03's scenario) has no test

- Category: testability
- Path: `apps/web/src/components/PersonaDashboardShell.test.tsx` (missing case); implementation at `PersonaDashboardShell.tsx:131-140`
- Source: `docs/features/SHP-01/FLAGS.md` AF-03 ("`SHP-01-TC-02`'s four scenarios do not cover it"); PLAN.md §7 Test Strategy
- Description: None of the four existing `PersonaDashboardShell.test.tsx` cases pass a defined `signedInUser` together with an invalid `persona` — the one combination `avatarColorStyle()`'s catch branch exists for. AF-03 already flags this gap for human triage; it remains open in the code as written.
- Suggested fix: Add a fifth case — `signedInUser` defined, `persona="cio"` (or the resolver-error sentinel) — asserting the identity avatar renders with `color: #5b6472` / `background: #e4e7ec` and still shows the real name/jobTitle/initials.

## What went well

- File plan discipline: all 15 `file_plan` entries (F-01..F-15) present, nothing extra under `apps/web/` — zero scope-creep.
- D-01's field-name isolation, D-02's shared-color-source guarantee, D-03's single-prop fail-loud design, and D-05's neutral identity fallback are all implemented exactly as decided.
- Tests assert real, jsdom-normalized values (hex→rgb conversion in `ProgramContext.test.tsx`) rather than re-testing the implementation against itself, and TC-04's p95 methodology (nearest-rank, cold renders, cleanup outside the timed window) is genuinely rigorous.
- AF-01/02/03/04/05/06/07 were all independently re-verified against their stated resolutions — no new information changes any of their triage status.

## Recommendation

**PASS WITH WARNINGS.** No CRITICAL, one HIGH (F-1), non-blocking per the verdict rule but should be fixed before any of ARC-01/DEV-01/PMD-01/EMD-01 plan against `docs/requirements/api.md#persona-shell` — the `icon` field is presently guaranteed-wrong and cheapest to correct now, before a consumer exists. F-2/F-3/F-4 are follow-up quality items, not blockers.

## Carry-forward (for orchestrator's `pending_carry_forward`)

- `SHP-01-icon-field-mockup-mismatch` (from F-1) — `program.icon` should be replaced with a type-derived avatar abbreviation before any consuming story (ARC-01/DEV-01/PMD-01/EMD-01) plans against the `persona-shell` contract.
- `SHP-01-D06-neutral-hex-duplication` (from F-2) — move `avatarColorStyle()`'s fallback pair into `PersonaDashboardShell.module.css`.
