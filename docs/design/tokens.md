# Design tokens

Extracted 2026-08-27 from `mockups/`. Machine-readable copy in `schema.json` § tokens.

The mockups use **inline styles only** — no CSS custom properties, no utility classes. These values
must be re-expressed as real tokens when the Next.js UI is built; nothing in the mockups can be
imported directly.

## Typography

| Token | Value |
|---|---|
| `font-sans` | `'Plus Jakarta Sans', system-ui, sans-serif` |
| `font-mono` | `'JetBrains Mono', monospace` — numerics and KPI glyphs |

Scale, in use-frequency order: `12.5` · `13` · `15` · `10.5` · `12` · `11` · `13.5` · `11.5` ·
`22` · `14` · `20` · `10.8` · `16` · `17` px, plus `25px` for KPI values and `19px` for page titles.
The fractional sizes are pervasive and deliberate — round them only as a conscious decision.

Added 2026-09-18 (SHP-04, `DECISIONS.md` D-03/D-04) from the Artifacts generated panel
(`DESIGN.md` § Token gaps) — three steps this region introduces:

| Token | Value | Role |
|---|---|---|
| `13.5px` / `600` | row name |
| `16px` / `800`, `letter-spacing:-.4px` | row count |
| `15px` / `700`, `letter-spacing:-.2px` | card title — distinct from OVW-04's `14px` section heading |

## Color

| Role | Hex |
|---|---|
| Primary / brand | `#2a6fdb` |
| Primary tint (icon tiles) | `#eef3fb` |
| Ink — headings, avatar fill | `#0f1a2e` |
| Success | `#1f8a5b` |
| Success tint | `#eaf6ef` |
| Accent — purple | `#6a4fd0` |
| Accent — terracotta | `#d97757` |

Text ramp, dark to light: `#5b6472` · `#7a828f` · `#8a93a1` · `#9aa2ae` · `#a2abb8`

Border and surface ramp: `#e4e7ec` · `#e6e9ef` · `#e9ebef` · `#eef0f3` · `#f0f1f4` · `#f2f4f7` ·
`#f4f5f7` · `#fafbfc`

No dark palette exists in the mockups. If the app needs one, it is a new design decision.

### Persona colors

Extracted 2026-09-03 (SHP-01, `DECISIONS.md` D-04) from the ARC/DEV/PMD/EMD mockups' persona tag
pill and signed-in-identity avatar circle — both use the same color per persona, byte-exact across
all four mockups.

| Persona | Persona key | Tag / avatar color | Tag pill background |
|---|---|---|---|
| Architect | `architect` | `#6a4fd0` | `#f0edfb` |
| Developer | `developer` | `#2a6fdb` | `#e9f1fd` |
| Product Manager | `product-manager` | `#d97757` | `#fdefe9` |
| Eng Manager | `engineering-manager` | `#1f8a5b` | `#eaf6ef` |

Added 2026-09-17 (PGD-05, `DESIGN.md` § "Avatar colour and initials") from the Program Detail
mockup's project-team-panel avatar circles — the one persona color absent from the ARC/DEV/PMD/EMD
set above. No tag-pill background is recorded because this role does not appear in the
persona-tag-pill mockups the table above was extracted from; only the avatar/circle color is
sourced.

| Persona | Persona key | Tag / avatar color | Tag pill background |
|---|---|---|---|
| QA Engineer | `qa-engineer` | `#d1495b` | N/A — not present in the persona-tag mockups |

**Reused as the artifact-type categorical palette (SHP-04).** Added 2026-09-18 (SHP-04,
`DESIGN.md` § Token gaps) — the Artifacts generated panel (`ArtifactsPanel`) re-uses the
Architect, Developer, Product Manager and Eng Manager `color`/`bg` pairs above verbatim for its
`PRD`/`US`/`TC`/`AD` tag chips, with **no semantic link**: `US` (User stories) does not mean "the
architect's artifact". Treat this as a shared colour ramp only. Do not "fix" a pair to align with
its persona, and if a future persona re-colour touches this table, check `ArtifactsPanel` for
unintended fallout before shipping.

### Program type colors

Extracted 2026-09-03 (SHP-01, `DECISIONS.md` D-04) from the Engineering Manager mockup's `tMap` —
the program-context block's `avatarStyle`/`typeChip` color source, keyed by `program.type`.

| Program type | Color | Background | Avatar abbreviation |
|---|---|---|---|
| Migration | `#2a6fdb` | `#eaf1fc` | `M` |
| Greenfield feature development | `#1f8a5b` | `#e8f5ee` | `G` |
| Brownfield feature development | `#7c5cff` | `#efebff` | `B` |
| Maintenance | `#c08a1e` | `#fdf3e0` | `MT` |

`.harness/program.yaml`'s manifest enum (`Greenfield|Brownfield|Upgradation|Migration|Maintenance`)
uses short names for two of the above. Added 2026-09-08 (`docs/stories/ING-10.md` AC-10,
`docs/features/ING-10/REQUIREMENTS.md` FR-6) — same approved pairs as their long-form entries,
no new colour introduced:

| Program type (short name) | Color | Background | Avatar abbreviation |
|---|---|---|---|
| Greenfield | `#1f8a5b` | `#e8f5ee` | `G` |
| Brownfield | `#7c5cff` | `#efebff` | `B` |

**`Upgradation` — open gap, not an oversight.** The manifest enum's fifth value has no colour and
no avatar abbreviation anywhere in the design source. A previously-assumed pair was rejected
(`docs/stories/ING-10.md` 2026-09-08 Decision log entry) in favour of "documented fallback, invent
nothing" (research condition C-3, `docs/features/ING-10/REQUIREMENTS.md` FR-6) — do not add a
guessed hex here. It renders with `Migration`'s blue via `programStyle.ts`'s
`?? PROGRAM_TYPE_COLORS["Migration"]` fallback, deliberately, until a real design token is
supplied.

### Artifact tag-chip colors

Extracted 2026-09-18 (SHP-04, `DECISIONS.md` D-03) from the Artifacts generated panel
(`DESIGN.md` § Presentation constants, decode L899–905, all three ARC/DEV/PMD mockups
byte-identical). Four of the five tag-chip pairs reuse § Persona colors verbatim as a categorical
palette — no new colour, see the note under that table. `API` is the exception:

| Tag | Color | Background |
|---|---|---|
| `API` | `#c08a1e` (existing — § Program type colors `Maintenance`, reused at a third role) | `#fef4e6` (**new** — genuinely new tint, not tokenised elsewhere; distinct from `#fdf3e0`, the `Maintenance` program-type background) |

**Contrast — standing carry-forward, not fixed here.** Four of the five tag-chip fg/bg pairs fail
WCAG AA (4.5:1 normal text, 3:1 non-text) as drawn: `PRD` `#2a6fdb`/`#e9f1fd` 4.20:1, `TC`
`#1f8a5b`/`#eaf6ef` 3.91:1, `API` `#c08a1e`/`#fef4e6` 2.80:1, `AD` `#d97757`/`#fdefe9` 2.78:1 —
`AD` and `API` fall below even the 3:1 non-text bar. Only `US` `#6a4fd0`/`#f0edfb` (5.00:1) clears
AA. These are the same pairs already shipping as persona tag pills (§ Persona colors, SHP-01), so
a fix is a token-level change with blast radius across all six dashboards — reproduced
byte-exactly from the mockup here, not diverged from unilaterally, and not this story's to fix
(`DESIGN.md` § Design QA / § Open design items for the gate #2). The tag abbreviation is
redundant decoration next to the full-contrast row name, so the failure does not block the
`NFR-accessibility` requirement, but it is recorded honestly rather than silently shipped as if
passing.

### Adoption indicator colors

Extracted 2026-09-10 (OVW-01, `DECISIONS.md` D-06) from the CIO Portfolio Dashboard mockup's
embedded sample-data script (`adoptionLegend`/`adoptionBarNot`, ~L761–766). "Using AI SDLC" reuses
the existing Primary/brand token above; "Not yet adopted" uses two *different* new hex values for
its two roles — legend swatch vs. bar-segment background — matching the mockup's own script.

| Role | Color |
|---|---|
| Using AI SDLC (bar segment + legend swatch) | `#2a6fdb` (existing Primary/brand) |
| Not yet adopted — legend swatch | `#c3c9d2` |
| Not yet adopted — bar segment background (also the zero-state flat-bar color) | `#dfe3e9` |

### Month-over-month (MoM) chip colors

Extracted 2026-09-18 (OVW-04, `DECISIONS.md` D-05) from the Program Board mockup's `momColor`/
`momBg` script (`DESIGN.md` § MoM change indicator). The mockup's own logic (`up = mom >= 0`) is
binary and has no neutral branch — the `flat` pair below is the one entry in this table that is
PO-approved, not mockup-sourced, recorded here so it is a token rather than a magic number in
component code.

| Direction | Color | Background |
|---|---|---|
| Up | `#1f8a5b` | `#e8f5ee` |
| Down | `#d1495b` | `#fdeaec` |
| Flat (PO-approved, not mockup-sourced) | `#5b6472` | `#f0f1f4` |

## Radius

`18px` modal panel · `16px` cards · `20px` pills and chips · `11px` icon tiles · `10px` · `9px`
brand mark, tag chip tile · `8px` controls · `6px` chips · `4px` · `2px` dots · `50%` avatars.

`18px` added 2026-09-17 (PGD-05 T-16, `DESIGN.md` § Token gaps) from the EMD popup panel — the
system's only modal, one radius step above the `16px` card token.

`9px` tag-chip use added 2026-09-18 (SHP-04, `DESIGN.md` § Token gaps) from the Artifacts
generated panel — the existing `9px` step (brand mark) reused, not a new radius value, on a
`32×32` square-ish tile distinct from the `20px` pill radius the persona tag / program-type chips
use.

## Elevation

Two shadows: `0 1px 2px rgba(15,26,46,.04)` on cards, and `0 24px 60px rgba(15,26,46,.28)` on a
modal panel. The design is border-led, not shadow-led — the modal shadow is the one legitimate
exception, added 2026-09-17 (PGD-05 T-16, `DESIGN.md` § Token gaps) from the EMD popup panel.

## Overlay

Modal overlay scrim: `rgba(15,26,46,.42)` — the Ink token (`#0f1a2e`) at 42% opacity. Added
2026-09-17 (PGD-05 T-16, `DESIGN.md` § Token gaps) from the EMD popup overlay; no other surface in
the system uses a scrim.

## Layout

| Token | Value |
|---|---|
| Content max width | `1360px` |
| Content padding | `24px 34px 44px` |
| Section gap | `24px` |
| Card padding | `18px 19px` |
| Grid gap | `16px` |
| KPI grid | `repeat(auto-fit, minmax(190px, 1fr))` |

Header is sticky and translucent: `background:#ffffffcc` with `backdrop-filter: blur(8px)`,
`z-index:5`, above a `1px solid #e9ebef` rule.

### Tile sizes

No prior token section collected these — recorded here for the first time (SHP-04,
`DESIGN.md` § Token gaps), not an established convention, just the observed set of square
avatar/tile sizes across the mockups:

| Size | Use |
|---|---|
| `26×26` | header avatar tile |
| `32×32` | artifact tag-chip tile (SHP-04, added 2026-09-18) |
| `34×34` | identity avatar / nav glyph |
| `46×46` | program avatar |

## Card recipe

```css
background: #fff;
border: 1px solid #e6e9ef;
border-radius: 16px;
padding: 18px 19px;
box-shadow: 0 1px 2px rgba(15, 26, 46, .04);
```

## Responsive

CLAUDE.md declares web desktop + mobile responsive. The mockups are **desktop-only** — a fixed
`1360px` column with no breakpoints. Mobile layout is undesigned and will need its own pass.
