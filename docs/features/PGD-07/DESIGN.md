# DESIGN: PGD-07 — Program Detail brand bar: signed-in identity block (shell retrofit)

**Provenance**: hand-authored 2026-09-16 during `/arh-plan-requirements` Phase 2. `ux-agent` is not
installed in this repo (`.claude/agents/` has no `ux-agent.md`) — the standing condition OVW-01 first
reclassified and OVW-05 recorded as its fourth occurrence. This file was written directly from the
design source instead of generated. **The mockup, not this file, is the source of truth on any
disagreement.**

**This story composes; it does not redesign.** Every region below is already specified by
[`docs/features/OVW-05/DESIGN.md`](../OVW-05/DESIGN.md) and already built in
`PersonaDashboardShell.tsx`. This file states only what is *new for this page*: which regions appear,
what data reaches them here, and the three states on this route. Nothing about the shell's geometry,
copy, focus rules, or markup is re-specified — read OVW-05's file for those.

**Design source**: `docs/design/mockups/Program Detail.html` (PGD epic, `docs/design/schema.json`) for
the page; `docs/design/mockups/CIO Portfolio Dashboard.html` (OVW epic) for the brand-bar reference
OVW-05 specced against. Both are Claude Design canvas exports — decode before reading, per
`docs/design/README.md` § "These are bundler outputs". Line numbers below are into those decodes.

## Finding: Program Detail's own mockup already carries the brand bar

`Program Detail.html` L369–385 holds a `<!-- BRAND BAR -->` region that is **byte-identical** to
`CIO Portfolio Dashboard.html` L376–392 — verified 2026-09-16 by `diff` over both decodes, zero
differences across all 16 lines. This story is therefore not porting a foreign region onto a page that
never had one; it is restoring the region the PGD mockup itself specifies and that
`ProgramDetailView.tsx` skipped by bypassing `PersonaDashboardShell`. `CLAUDE.md`'s "do not invent UI"
rule is satisfied by the PGD mockup alone.

Consequence: OVW-05's brand-bar spec applies here **verbatim, not by analogy**. No geometry, spacing,
or type value differs between the two pages' brand bars.

## Scope

Per `REQUIREMENTS.md` § Screen inventory — four entries, all inside or below one region.

| # | Screen-inventory entry | Region | Component | Mockup anchor |
|---|---|---|---|---|
| 1 | Program Detail brand bar (static) | `BRAND BAR`, left half | `PersonaDashboardShell.tsx` (shipped, SHP-01) | `Program Detail.html` L370–377 |
| 2 | Program Detail identity block | `BRAND BAR`, right half | same (shipped, SHP-01 + OVW-05) | `Program Detail.html` L378–384 |
| 3 | Program Detail sign-out control | `BRAND BAR`, right half, last child | same (shipped, OVW-05 deviation A) | **none — inherited deviation**, see below |
| 4 | Program Detail header + summary cards (unchanged) | `HEADER` + `PROJECT SUMMARY` | `ProgramDetailHeader` / `ProgramSummaryCards` (shipped, PGD-01) | `Program Detail.html` L387–423 / L427–446 |

Entries 1–3 are `PersonaDashboardShell`'s own children. Entry 4 becomes the shell's `children` — its
markup is untouched by this story.

**Placement**: the brand bar is the shell's first child and sits **above** `ProgramDetailHeader`, which
is the mockup's own vertical order (`BRAND BAR` L369 precedes `HEADER` L387). No spacer, divider, or
wrapper is added between them — the brand bar's own `border-bottom:1px solid #eef0f3` and the header's
`border-bottom:1px solid #e9ebef` are adjacent as the mockup has them.

---

## Region 1 — brand bar, left half (static)

Logo tile + `AgentRise Harness` + `AI SDLC Governance`. Shipped unchanged by SHP-01; specified in
`OVW-05/DESIGN.md` § "Recorded deviation B" (which reproduces the same three elements byte-exactly).
Nothing on this page changes it.

Renders **unconditionally**, including while persona is unresolved — this is what makes the loading
state below non-empty.

## Region 2 — brand bar, right half (signed-in identity block)

Geometry, bindings and the `name === null` neutral fallback: **see `OVW-05/DESIGN.md` § "Region 1 —
`BRAND BAR`, right half"**. Not restated. What is specific to this page:

### The mockup's identity values are sample data

Both mockups hardcode `Elena Vasquez` / `Chief Information Officer` / `EV` and a `#0f1a2e` avatar —
the `cio` persona. **These are canvas sample values and must never ship**, not as fallback copy, not as
a default, not as the value used when `/api/me` is slow or fails. `docs/design/README.md` § Recorded
divergences states the rule; OVW-05 applied it to `/overview`; it applies identically here.

Program Detail is reached by **all five personas**, so unlike `/overview` this page routinely renders
values the mockup never shows. That is correct, not a divergence:

| `persona` from `GET /api/me` | `jobTitle` (`PERSONA_DISPLAY[persona].jobTitle`) | Avatar / tag colour (`formatPersonaTag(persona).color`) |
|---|---|---|
| `cio` | Chief Information Officer | `#0f1a2e` |
| `architect` | Architect | `#6a4fd0` |
| `developer` | Developer | `#2a6fdb` |
| `engineering-manager` | Engineering Manager | `#1f8a5b` |
| `product-manager` | Product Manager | `#d97757` |

Colours are `docs/design/tokens.md` § Persona colors, extracted from the mockups. The four non-`cio`
job titles are the plain role names, **not** the ARC/DEV mockups' `Principal Architect` /
`Senior Developer` — those assert a seniority the system holds nowhere, and
`docs/design/README.md` § Recorded divergences already logs the weaker-true-string rule. `jobTitle` is
composed client-side from `PERSONA_DISPLAY`; the `/api/me` wire ships `{name, persona}` only
(`MeResponse`, `extra="forbid"`), so there is no wire field to render even if one appeared.

### `program: undefined` — the header region must stay closed

`PersonaDashboardShell` gates its own header region on `program !== undefined`. `ProgramDetailHeader`
(PGD-01, shipped) **already renders the mockup's entire `<!-- HEADER -->` region** — program avatar,
name, type chip, persona pill, description (`Program Detail.html` L388–399). Passing a real `program`
to the shell would open the shell's gate and paint a *second* program header directly above the one
`ProgramDetailHeader` paints, duplicating the avatar/name/type-chip/description.

So `<PersonaDashboardShell program={undefined} …>` is passed **explicitly** (FR-2, AC-2), and this is
the deliberate design intent, not an omission. The shell contributes the brand bar; `ProgramDetailHeader`
remains the sole renderer of the program header region. Reviewers seeing `program={undefined}` next to
a page that plainly has a program should read this paragraph, not "fix" it.

## Region 3 — sign-out control

**The same shell control OVW-05 ships.** Not a Program-Detail variant, not a fork, not a second
implementation (AC-9). It is the last child of the shipped `.identity` flex row, renders on
`!isLoading` (so in *both* the populated and the `name === null` neutral branch), and submits the
zero-JS `<form action="/logout" method="get">`. Full spec — placement rationale, type scale, the
`#5b6472` → `#2a6fdb` colour pair, focus ring, and why a form rather than a client button — is
`OVW-05/DESIGN.md` § "Recorded deviation A". Nothing about it is re-decided here.

**Inherited deviation, re-affirmed.** The control appears in **no** mockup, including this page's —
OVW-05 verified zero `sign out` / `signout` / `log out` / `logout` matches across all six decodes. Its
authority is `docs/stories/OVW-05.md` § Decision log (2026-09-11, explicit user direction). PGD-07
inherits that decision rather than re-raising it; the story's own Problem statement ("cannot sign out
without navigating back to a page that has one") is the direct consequence of the control existing
everywhere the shell does.

## Region 4 — header + summary cards (unchanged)

`ProgramDetailHeader` + `ProgramSummaryCards`, PGD-01, shipped. This story makes them
`PersonaDashboardShell`'s `children` and changes nothing else — no markup, no props, no styles, and no
change to their existing Populated / Loading / Error states (including the client-side switcher
reload). Listed here only so the inventory is complete.

---

## States

Three states across regions 1–3, plus the `name === null` sub-case. Region 4's states are PGD-01's and
are unaffected.

| State | Trigger | Brand bar (R1) | Identity block (R2) | Sign-out (R3) |
|---|---|---|---|---|
| **Loading** | `persona === undefined` — `/api/me` not yet resolved | renders, static | **absent entirely** | absent |
| **Populated** | `/api/me` → `{persona, name}` | renders | name + `jobTitle` + initials avatar in the persona's colour | renders |
| **Populated-neutral** | `persona` resolved, `name === null` | renders | neutral `34×34` gray circle, **no initials**, `aria-hidden="true"` | renders |
| **Error** | `403` or unrecognized persona | renders | neutral gray `Persona unavailable` badge + visually-hidden `aria-live="assertive"` announcement | renders |

**Loading is a static brand bar and nothing else.** No persona tag, no subtitle, no program-context
block, no identity block, and — explicitly — **no skeleton, shimmer, or placeholder** of any kind. The
whole right half is omitted, not stubbed. This is SHP-01's FR-5 flash-prevention rule: a skeleton that
resolves in ~100ms reads as a glitch, and a placeholder avatar would flash a wrong colour before the
real persona arrives. Do not add one.

**Populated-neutral is never `Elena Vasquez` and never blank.** The shipped D-05 fallback is a plain
circle on `var(--neutral-unresolved-bg)` with no glyph, marked `aria-hidden="true"` because a
contentless decorative circle has nothing to announce. Adding `aria-hidden` to the circle does **not**
hide the row — the sign-out button beside it stays in the accessibility tree.

**Error renders the neutral badge, never a guessed persona.** `page.tsx` passes the existing
persona-resolution-error sentinel (FR-3) rather than omitting `persona` — omitting it would be read as
Loading and silently suppress the identity block instead of reporting the failure. The shell's shipped
`PersonaTagError` path (`PersonaDashboardShell.tsx:241`, `:244`) then renders
`Persona unavailable` on the shared `--neutral-unresolved-*` pair plus the visually-hidden
`aria-live="assertive"` region announcing **"Unable to load your dashboard view."** This is the existing
shell path, reached for the first time on this route — no new error treatment.

Fail-closed: there is no state in which this page paints a persona the caller does not hold.

---

## Design QA — contrast

PGD-07 introduces **no new colour pair**. Every pair it renders was audited in
`OVW-05/DESIGN.md` § "Design QA — contrast audit" (the identity block, sign-out control, focus ring)
or `SHP-01` § Design QA (the shell's 22 pairs). The four non-`cio` avatar pairs are the only ones
newly reachable here — `#ffffff` on `#6a4fd0` / `#2a6fdb` / `#1f8a5b` / `#d97757` — and all four were
audited by SHP-01 when the persona tags shipped.

**Carry-forward, not fixed here — `DQA-1-preauth-contrast` (OVW-05).** The `#8a93a1` grey used by the
brand bar tagline and the identity block's `jobTitle` is **3.10:1** on `#ffffff` and fails WCAG AA's
4.5:1 for normal text. Both surfaces render on this page, so PGD-07 reproduces the failure. It is the
mockups' own value; darkening the token has blast radius across all six dashboards and is a design
decision, not an implement-phase edit. Recorded and inherited, per OVW-05's disposition — **do not
unilaterally darken `#8a93a1` in this story.**

## Keyboard and assistive tech

Inherited wholesale from `OVW-05/DESIGN.md` § "Keyboard and assistive tech". Page-specific note only:
the brand bar is the first region in DOM order, so tab order on `/programs/<id>` runs brand bar →
sign-out → `ProgramDetailHeader`'s back-link and program switcher → summary cards. The sign-out control
is reached before the page content, as it is on `/overview` — consistent placement across both routes,
which is the point of composing the shell rather than forking it.

## Form factors

**Desktop-only.** `docs/design/README.md` and `docs/design/tokens.md` § Responsive record all six
mockups as a fixed `1360px` column with no breakpoints — against `CLAUDE.md`'s "desktop + mobile
responsive" target. The brand bar carries no breakpoint, no wrap rule, and no mobile composition in
either mockup. Nothing to specify; nothing to invent. `REQUIREMENTS.md` § Scope already places
mobile/responsive layout out of scope.

## Tokens

`docs/design/tokens.md`. The mockups use **inline styles only** — no custom properties, no utility
classes — so no token reference exists in the markup to map back. All values reach this page through
already-shipped CSS Module rules in `PersonaDashboardShell.module.css`; this story authors no new rule
and no new literal. Only `formatPersonaTag()`'s `{color, background}` pair crosses as a `style` prop
(SHP-01 D-06), unchanged.

## Open design items for the gate

**None.** Every region is already built and already specified; this story supplies props to shipped
markup. OVW-05's four open items are either settled in shipped code or belong to `/overview` and
`/login` surfaces this story does not touch.

One risk recorded, not an open item: **`DQA-1-preauth-contrast` reaches a fifth surface.** The
inherited `#8a93a1` 3.10:1 failure now renders on `/programs/<program_id>` as well. Same defect, wider
audience — carried forward with OVW-05's, not fixed here.
