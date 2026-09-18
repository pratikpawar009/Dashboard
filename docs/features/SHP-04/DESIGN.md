# DESIGN: SHP-04 — Artifacts generated panel

**Provenance**: hand-authored 2026-09-18 during `/arh-plan-requirements` Phase 2. `ux-agent` is not
installed in this repo — `.claude/agents/` has no `ux-agent.md` — the same gap SHP-01, PGD-01,
OVW-01, OVW-05 and OVW-04 each hit and recorded in their own `DESIGN.md` files. This is the
**sixth** occurrence; OVW-01 reclassified it from surprise to standing condition and carried it
forward for a decision on whether to install the agent. Nothing new to add. This file was written
directly from the decoded design source, not generated. It is a **pre-implementation spec**: neither
the route nor the component exists. **The mockup, not this file, is the source of truth on any
disagreement.**

**Design source**: `docs/design/mockups/{Architect,Developer,Product Manager} Dashboard.html`
(`docs/design/schema.json` → `designSystem.pages.features.ARC` / `.DEV` / `.PMD`). Claude Design
canvas exports — decoded per `docs/design/README.md` § "These are bundler outputs". Each decode is
1,099 lines / ~63.2 KB. Line references below are into that decode.

## Scope

One region, one screen per `REQUIREMENTS.md` § Screen inventory. The decoded document's section
comments are `BRAND BAR`, `HEADER`, `CONTENT`, `MY USAGE`, `YOUR DAILY TOKEN CONSUMPTION`,
`YOUR COMMANDS`, `MY SESSIONS TABLE`, `PROGRAM SUMMARY`, `ARTIFACTS + RELEASES`, `PROJECT TEAM`,
`COMMANDS + COMPLIANCE`, `CONSTITUTION`, `MEMBER COMMAND POPUP`. **This story owns the `ARTIFACTS`
card only** (L539–553), the left half of the `ARTIFACTS + RELEASES` two-up section.

| Screen | Region | Component | Mockup anchor |
|---|---|---|---|
| Artifacts generated panel | embedded panel on `/architect`, `/developer`, `/product-manager` (ARC-01/DEV-01/PMD-01) | `ArtifactsPanel` (new) | `<!-- ARTIFACTS -->` L539–553 |

Explicitly **not** in scope though the same section renders it: `RELEASES VIA HARNESS` (L556–594),
the right half of the same grid. Nor the parent grid's own composition, which belongs to
ARC-01/DEV-01/PMD-01 (`REQUIREMENTS.md` § Scope already lists dashboard composition as out).

## Cross-page identity — verified, no divergence

Phase 1's key fact is **confirmed by diff, not assumed**. The three decodes differ in exactly four
regions, all persona identity chrome in `BRAND BAR` (L380–381) and `HEADER` (L390–391) — signed-in
name, job title, avatar initials + circle colour, persona tag pill, and the `"<Persona> overview"`
page title. Everything else, asset UUIDs aside, is byte-identical.

The `ARTIFACTS` markup block (L539–553) and its sample-data array (L899–905) are **byte-identical
across all three files** — verified by `diff` on both ranges, zero output. One component, no
persona branching, no persona-coloured chrome inside the panel. No divergence to report.

The persona-identity diffs that do exist are already recorded (`docs/design/README.md`
§ Recorded divergences: `Principal Architect` → `Architect`, `Senior Developer` → `Developer`;
sample names never ship) and belong to SHP-01/OVW-05, not this story.

---

## Region — `ARTIFACTS`

### Card shell (L540)

```
background:#fff; border:1px solid #e9ebef; border-radius:16px; overflow:hidden
```

`overflow:hidden` is load-bearing — it clips the last row's `border-bottom` against the rounded
corner. See § Row anatomy.

The parent section (L538) is
`display:grid; grid-template-columns:repeat(auto-fit,minmax(min(100%,360px),1fr)); gap:16px; align-items:start`
— **intrinsically fluid**, unlike most of this design. The panel is a grid child with a `360px`
minimum and no fixed width; it must not assume one. `align-items:start` means it does **not**
stretch to the taller Releases card's height.

### Panel header (L541–543) — literal copy, static, never bound

| Element | Line | Exact text / form |
|---|---|---|
| Header block | L541 | `padding:18px 20px 14px; border-bottom:1px solid #f0f1f4` |
| Title | L542 | `Artifacts generated` — `font-size:15px; font-weight:700; letter-spacing:-.2px`, inherits body ink `#151a22` |
| Subtitle | L543 | `Outputs produced on this program` — `font-size:12.5px; color:#7a828f; font-weight:500; margin-top:3px` |

Both strings are **static literals** — no `{{ }}` binding, no program name interpolated into either.
The subtitle says "this program" generically; it does not render the program's name. Do not
parameterise it.

There is no section-heading dot here, unlike OVW-04's `PROGRAM LEADERBOARD` — this is a card with an
internal header, not a page section with a dot-prefixed heading.

### List construct (L545–546)

```html
<div style="padding:6px 20px 14px">
  <sc-for list="{{ artifacts }}" as="a" hint-placeholder-count="5">
```

The list body's own padding is `6px 20px 14px` — note the `20px` horizontal matches the header's,
and the `6px` top is deliberately smaller than the header's `14px` bottom because the first row
carries its own `12px` top padding.

`hint-placeholder-count="5"` is a **contract, not a sample size**, per the reading PGD-01
established and OVW-01/OVW-04 reaffirmed: the loading state renders exactly **5** placeholder rows
at populated geometry with text suppressed. Here the contract and the data agree exactly and
permanently — `SHP-04-FR-1` fixes `items` at exactly 5 entries, always, so this panel never has a
skeleton-count-vs-page-size question of the kind OVW-04 § gap 2 raised. 5 is the closed canonical
vocabulary, not a page.

### Row anatomy (L547–551)

Row container (L547): `display:flex; align-items:center; gap:12px; padding:12px 0; border-bottom:1px solid #f4f5f7`

| # | Element | Line | Binding | Style |
|---|---|---|---|---|
| 1 | Tag chip | L548 | `a.tag`, `a.bg`, `a.color` | `32×32` · `border-radius:9px` · `background:{{a.bg}}` · `color:{{a.color}}` · centred flex · `13px` / `800` · `font-family:'JetBrains Mono', monospace` · `flex:none` |
| 2 | Name | L549 | `a.name` | `flex:1` · `13.5px` / `600` · inherits body ink `#151a22` |
| 3 | Count | L550 | `a.count` | `16px` / `800` · `letter-spacing:-.4px` · inherits body ink `#151a22` |

Three notes:

1. **The tag chip is a square-ish rounded tile, not a pill.** `border-radius:9px` on a `32×32` box —
   the same family as the `26px`/`8px` header avatar tile, *not* the `border-radius:20px` pill the
   persona tag and program-type chips use. It is monospace; the name and count are not.
2. **The count has no `flex` and no explicit alignment.** The name's `flex:1` pushes it right; the
   count sizes to content. Digits are **not** monospace here (only the tag is), so counts do not
   column-align across rows. That is the mockup as drawn.
3. **Every row carries `border-bottom`, including the last.** The card's `overflow:hidden` plus the
   list body's `14px` bottom padding means the fifth rule renders as a visible hairline above the
   card's bottom edge, not flush with it. Reproduce it; do not add a `:last-child` rule stripping it
   — the mockup shows five rules under five rows.

### Presentation constants — the five canonical pairs

**This resolves `REQUIREMENTS.md`'s single `[NEEDS CLARIFICATION]`.** The sample data Phase 1 could
not find *is* in the embedded script, at decode **L899–905** of all three files, byte-identical:

```js
const artifacts = [
  { tag: 'PRD', name: 'Product Requirement Docs', count: '4',   bg: '#e9f1fd', color: '#2a6fdb' },
  { tag: 'US',  name: 'User stories',             count: '48',  bg: '#f0edfb', color: '#6a4fd0' },
  { tag: 'TC',  name: 'Test cases',               count: '136', bg: '#eaf6ef', color: '#1f8a5b' },
  { tag: 'AD',  name: 'Architecture diagrams',    count: '7',   bg: '#fdefe9', color: '#d97757' },
  { tag: 'API', name: 'API specifications',       count: '11',  bg: '#fef4e6', color: '#c08a1e' },
];
```

Unlike OVW-04's `tMap`/`momColor`, this is a **flat literal array, not a derivation** — there is no
map keyed by type, no function. The values below are transcribed, not computed.

| # | Canonical type (`_CANONICAL_ARTIFACT_TYPES`) | `tag` | `name` | `color` | `bg` |
|---|---|---|---|---|---|
| 1 | `prd` | `PRD` | `Product Requirement Docs` | `#2a6fdb` | `#e9f1fd` |
| 2 | `user_story` | `US` | `User stories` | `#6a4fd0` | `#f0edfb` |
| 3 | `test_case` | `TC` | `Test cases` | `#1f8a5b` | `#eaf6ef` |
| 4 | `arch_diagram` | `AD` | `Architecture diagrams` | `#d97757` | `#fdefe9` |
| 5 | `api_spec` | `API` | `API specifications` | `#c08a1e` | `#fef4e6` |

**Array order is the contract** and it matches `_CANONICAL_ARTIFACT_TYPES` position-for-position, as
`SHP-04-FR-1` asserts. Two independent orderings agreeing is worth stating: the PRD did not need to
re-derive the order, and the mockup independently confirms it.

**Four of the five pairs are the persona palette, reused.** `docs/design/tokens.md` § Persona colors
records exactly these four `color`/`bg` pairs — Architect `#6a4fd0`/`#f0edfb`, Developer
`#2a6fdb`/`#e9f1fd`, Product Manager `#d97757`/`#fdefe9`, Eng Manager `#1f8a5b`/`#eaf6ef`. The
artifacts panel re-uses that ramp as a categorical palette with **no semantic link** — `US` is not
"the architect's artifact". Treat the coincidence as a shared colour ramp, never as meaning, and do
not "fix" a pair to match a persona. Only `API`'s `#c08a1e`/`#fef4e6` is outside that set: the
colour is `tokens.md`'s `Maintenance` program-type colour at a third role, and `#fef4e6` is a new
tint absent from `tokens.md` entirely. See § Token gaps.

#### `name` differs from the PRD — the mockup's strings ship

`SHP-04-FR-1`'s illustrative shape carries three shortened names. The design source is the
authority on rendered copy:

| `tag` | PRD FR-1 | **Mockup (ships)** |
|---|---|---|
| `PRD` | `PRDs` | `Product Requirement Docs` |
| `US` | `User stories` | `User stories` — agree |
| `TC` | `Test cases` | `Test cases` — agree |
| `AD` | `Arch diagrams` | `Architecture diagrams` |
| `API` | `API specs` | `API specifications` |

Three of five diverge. Not a contract mismatch — `name` is a server-owned presentation constant
either way, and nothing about the wire shape changes. It is a **copy** correction: ship the mockup's
strings. Recorded in § PRD-vs-mockup gaps so the PRD's example block is not implemented literally.

Note the longest, `Product Requirement Docs`, at `13.5px`/`600` inside a `360px`-minimum card with a
`32px` chip, `12px` gaps and `20px` padding either side, has roughly `250px` of measure before the
count. It fits at the minimum width; it is the string that would wrap first if the grid ever narrows
below `360px`. It has no `max-width` and no `white-space` rule — it wraps rather than truncates.

#### `count` is a string in the mockup, a raw int on the wire

The sample array carries `count: '4'` / `'48'` / `'136'` — **quoted strings**. `SHP-04-FR-1` ships
`count` as a **raw int**. This is a deliberate, already-decided divergence, not an oversight: the
mockup's quoting is a canvas-authoring artefact (every value in these exports is a string), and
`docs/design/README.md` § "Values arrive pre-formatted" is about *formatting*, not JSON type. No
magnitude suffixing applies — the mockup's own values are `4`/`48`/`136`, plain digits with no
`M`/`K`, and unlike `Total tokens` on OVW-04 there is no `fmtM` call anywhere near this array. The
frontend renders `String(count)` and adds nothing. Consistent with ADR-0009's raw-int split.

---

## States

| State | Rendering |
|---|---|
| Populated | exactly 5 rows in `_CANONICAL_ARTIFACT_TYPES` order — **order is the contract**, never re-sorted client-side, never sorted by count |
| Loading | exactly **5** placeholder rows (`hint-placeholder-count="5"`, L546) at populated geometry — `32×32` chip, full-width name bar, count bar — text suppressed. Panel header renders normally (it is static copy, nothing to load). Server-rendered per § Screen inventory, so reachable only via Suspense/streaming; spec'd because the mockup contracts it |
| Empty / zero-count (AC-3) | **the populated state with `0`s.** All 5 rows render, chips and names at full colour, `count` renders the digit `0`. There is no empty variant, no "no artifacts yet" copy, no dimming, no hidden rows — the mockup has none and `SHP-04-FR-1` guarantees 5 entries always. A brand-new program and a fully-productive one differ only in the digits |
| Error (403 non-authorized persona, AC-2) | the panel is **absent from the page** — not an inline error, not a disabled card. `governance_visibility` denies `cio`/`engineering-manager` before any read, and the mockup has no error region for this card. The parent dashboard page (ARC-01/DEV-01/PMD-01) owns what the grid does with one missing child; those three routes are only reachable by the three allowed personas anyway, so this state is defensive |
| Partial data | not reachable. The zero-fill contract means there is no per-row failure — every type always has a row |

The zero state deserves emphasis because it inverts the usual instinct: **`0` is a real, meaningful
value here** ("this program has produced no architecture diagrams"), not an absence to hide. The
live `dashboard` program already has `arch_diagram=0, api_spec=0` per `REQUIREMENTS.md` § Problem,
so two of five rows render `0` on day one.

---

## PRD-vs-mockup gaps

Raised, not designed around, per `CLAUDE.md` § Design system. None blocks the PRD.

1. **`name` strings differ on 3 of 5 rows** — § Presentation constants. The mockup's longer strings
   ship; `SHP-04-FR-1`'s example block should be corrected to match at the next PRD edit. No wire
   shape change.
2. **`count` typing** — mockup strings vs FR-1 raw int. Already decided in FR-1's favour and
   consistent with ADR-0009; recorded so a future reader diffing the mockup does not read it as
   drift. § `count` above.
3. **`bg`/`color` on the wire.** Already decided (PO binding decision, `docs/research/SHP-04.md`
   § Resolved questions #1, FR-1) — these ship as server-owned constants, following ADR-0009/0007.
   Noted only because `docs/design/README.md` § "The templates also bind presentation" tells readers
   *not* to copy the mockup here by default; this story has an explicit decision to do so, which is
   the documented escape hatch, not an oversight. This makes SHP-04 the **third** endpoint shipping
   CSS-valued fields.
4. **No `[NEEDS CLARIFICATION]` remains.** The one open item this file was asked to resolve is
   resolved from source above. `needs_clarification_count` should drop to `0` at the next PRD edit —
   this file does not change that field.

---

## Design QA — contrast audit

WCAG 2.2 relative-luminance formula; 4.5:1 normal text, 3:1 large text (≥18.66px bold) and non-text.

| Element | fg | bg | Ratio | Bar | |
|---|---|---|---|---|---|
| Panel title (15px/700) | `#151a22` | `#ffffff` | 17.46 | 4.5 | PASS |
| Row name (13.5px/600) | `#151a22` | `#ffffff` | 17.46 | 4.5 | PASS |
| Row count (16px/800) | `#151a22` | `#ffffff` | 17.46 | 4.5 | PASS |
| Panel subtitle (12.5px/500) | `#7a828f` | `#ffffff` | 3.88 | 4.5 | **FAIL** |
| Tag chip `US` (13px/800) | `#6a4fd0` | `#f0edfb` | 5.00 | 4.5 | PASS |
| Tag chip `PRD` | `#2a6fdb` | `#e9f1fd` | 4.20 | 4.5 | **FAIL** |
| Tag chip `TC` | `#1f8a5b` | `#eaf6ef` | 3.91 | 4.5 | **FAIL** |
| Tag chip `API` | `#c08a1e` | `#fef4e6` | 2.80 | 4.5 | **FAIL** |
| Tag chip `AD` | `#d97757` | `#fdefe9` | 2.78 | 4.5 | **FAIL** |
| Row rule (non-text) | `#f4f5f7` | `#ffffff` | 1.05 | 3.0 | **FAIL — decorative** |

**Every failure is the mockup's own value, reproduced byte-exactly** rather than diverged from
unilaterally — the same position SHP-01, OVW-05 and OVW-04 took. Three observations:

- **Four of five tag chips fail, `AD` and `API` badly** (2.78–2.80:1, below even the 3:1 non-text
  bar). This is the same systemic tint-on-tint chip recipe OVW-04 § Design QA flagged across the
  type and MoM chips; here it is worse because the warm pairs (`#d97757`, `#c08a1e`) are lighter
  foregrounds. The `#6a4fd0`/`#f0edfb` Architect pair is the only one that clears AA. Since these
  four pairs **already ship** as persona tag pills (`tokens.md` § Persona colors, SHP-01), any fix
  is a token-level decision with blast radius across all six dashboards. Standing carry-forward, not
  this story's to fix.
- **The tag is not the only label.** `a.name` sits immediately beside every chip in full-contrast
  ink, so the chip colour is never the sole indicator of artifact type — `REQUIREMENTS.md` § NFR
  Accessibility's requirement is satisfied by the mockup as drawn, independent of the chip's own
  contrast. The abbreviation text inside the chip is redundant with the name, not load-bearing.
- **`#7a828f` at 3.88:1** is the mockups' card-subtitle grey, already shipped on the Releases,
  Commands and Compliance cards. Same standing carry-forward `tokens.md` records for `#9aa2ae`.

Nothing here is fixed in this story. Darkening a global ramp value is a design decision, not an
implement-phase edit.

## Keyboard and assistive tech

- **The panel is entirely non-interactive.** No link, no button, no hover state, no click binding
  anywhere in L539–553 — unlike the Releases card beside it, which carries range buttons. Zero tab
  stops. Add no `tabindex`, no `role="button"`, no handler; a row is not a drill-down affordance and
  the design source offers no target for one.
- **Semantics.** Five label/value rows is a description list — `<dl>` with `<dt>` (chip + name) and
  `<dd>` (count), or a `<table>` with a visually-hidden caption. A flat stack of `<div>`s renders
  correctly but gives a screen reader no relationship between `Test cases` and `136`. Stated as the
  framework/WCAG-idiomatic fallback per `.claude/rules/project-standards.md`, not this team's
  convention — the repo has no existing label/value list pattern to match.
- **Heading.** `Artifacts generated` is the card's accessible heading; mark it as one at whatever
  level the parent dashboard's outline requires (the parent owns the level, not this panel).
- **The tag chip is redundant.** `PRD` beside `Product Requirement Docs` is decorative
  abbreviation — `aria-hidden="true"` on the chip avoids a screen reader announcing
  "PRD Product Requirement Docs 4". If the chip is kept in the accessible name, the monospace
  abbreviation may be spelled out letter-by-letter, which is worse than omitting it.
- **Counts need their unit from the name**, which the `<dl>` pairing above already supplies. No
  `aria-label` per count.
- No motion, no transition, no `prefers-reduced-motion` concern — the card declares none.

## Form factors

**Desktop-only.** `docs/design/README.md` and `docs/design/tokens.md` § Responsive both record all
six mockups as a fixed `1360px` column with no breakpoints, against `CLAUDE.md`'s "Web (desktop +
mobile responsive)" target. `REQUIREMENTS.md` § Screen inventory scopes this to the panel only.

This panel is the **unusually good case**: its parent grid (L538) is
`repeat(auto-fit,minmax(min(100%,360px),1fr))`, which already collapses the two-up
Artifacts/Releases pair to a single column below ~`736px` with no breakpoint, and the `min(100%,…)`
guard prevents the `360px` minimum from overflowing a narrower viewport. The rows themselves are
`flex` with `flex:none` on the chip and `flex:1` on the name — intrinsically fluid.

The one item for the eventual responsive pass, recorded rather than designed here: **the row has no
wrap rule**. Below roughly `280px` of content width the longest name (`Product Requirement Docs`)
wraps to two lines and the `align-items:center` row grows, which is graceful; but nothing has been
verified below the mockup's `360px` floor because no mockup renders it.

## Tokens

`docs/design/tokens.md` holds the extracted palette, type scale and radii. Literal values above are
byte-exact from the decoded inline styles; the mockups carry **inline styles only**, no custom
properties and no utility classes, so there is no token *reference* in the markup to map back.
Prefer the named token where one matches, fall back to the literal where it does not.

Matched: `primary` `#2a6fdb` · `success` `#1f8a5b` · `success tint` `#eaf6ef` · `border-100`
`#e9ebef` · `surface-200` `#f0f1f4` · `surface-150` `#f4f5f7` · `card` radius `16px` ·
`size-body-sm` `12.5px` · the full § Persona colors table (four of the five artifact pairs) ·
`#c08a1e` (§ Program type colors, `Maintenance`).

### Token gaps

Present in this region, absent from `tokens.md`. Added here for the record; adding them to
`tokens.md` is a T-task for implementation, not a decision this file makes.

| Value | Role |
|---|---|
| `#fef4e6` | `API` tag-chip background. **The only genuinely new colour in this region** — the `#c08a1e` it pairs with is tokenised (as a program-type colour) but this tint is not, and it is not the `#fdf3e0` the `Maintenance` program type uses. Two different tints of the same hue now ship |
| `#7a828f` | card-subtitle grey. Listed in `tokens.md`'s text ramp (L32) as a raw hex but carries no named role; this is its second documented use |
| `#151a22` | body ink — used by three values here. `tokens.md` records `ink` as `#0f1a2e`; `#151a22` is the mockups' `body{color}` (decode L358) and is a *different* value. Already noted by OVW-05 and OVW-04 § Tokens; third occurrence |
| `9px` radius | tag chip. `tokens.md` § Radius has no `9px` step (OVW-04 already flagged `12px` and `13px` missing) |
| `32×32` | tag chip tile. A fourth tile size alongside `26×26` (header), `34×34` (identity avatar / nav glyph) and `46×46` (program avatar) |
| `13.5px` / `600` | row name. `tokens.md` § Typography has no `13.5px` step |
| `16px` / `800`, `letter-spacing:-.4px` | row count |
| `15px` / `700`, `letter-spacing:-.2px` | card title. A card-header size distinct from OVW-04's `14px` section heading |

The four persona `color`/`bg` pairs need **no new token** — but `tokens.md` § Persona colors should
gain a note that the same four pairs double as the artifact-type palette with no semantic link, so a
future persona re-colour does not silently re-colour this panel. Recorded as a docs T-task.

## Open design items for the gate

1. **`name` copy correction** — § PRD-vs-mockup gaps item 1. The mockup's three longer strings ship;
   `SHP-04-FR-1`'s example block should be corrected. Mechanical, not a decision.
2. **Tag-chip contrast is systemically below AA** — four of five pairs land 2.78–4.20:1, two below
   even the non-text 3:1 bar. Already shipped as persona pills elsewhere; a token-level fix with
   six-dashboard blast radius. Standing carry-forward, not this story's.
3. **`#fef4e6` needs a `tokens.md` entry**, plus the persona/artifact shared-ramp note above. Docs
   T-task.
4. **Row semantics** (`<dl>` vs flat `<div>`s) — § Keyboard and assistive tech. No existing repo
   pattern to match; recommend `<dl>`. A structural call, not a visual one.

**Resolved, no longer open**: the exact tag abbreviation and hex `bg`/`color` pair per canonical
type — found at decode L899–905 of all three mockups, transcribed in § Presentation constants. The
PRD's one `[NEEDS CLARIFICATION]` is closed from source; no value in this file was invented.

None blocks the PRD. Items 1, 3 and 4 need action before the component is built; item 2 is a
standing carry-forward.
