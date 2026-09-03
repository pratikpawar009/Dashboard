# DESIGN: SHP-01 — Persona header/context shell

**Provenance**: hand-authored 2026-09-03 during `/arh-implement` flag triage (`FLAGS.md` AF-01/AF-02/AF-04,
verdict `accept`). `ux-agent` is not installed in this repo, so this file was written from the
authoritative design source rather than generated. It is therefore a **post-implementation record** of
what the code actually binds, plus the design QA the PRD routed here and nobody had yet run — not a
pre-implementation spec. Treat the mockups, not this file, as the source of truth on any disagreement.

**Design source**: `docs/design/mockups/{Architect,Developer,Product Manager,Engineering Manager} Dashboard.html`
(`docs/design/schema.json` → ARC/DEV/PMD/EMD epics). These are Claude Design canvas exports and must be
decoded before the markup is readable — see `docs/design/README.md` for the procedure. Decoded, the shell's
regions are `<!-- BRAND BAR -->` (line 368) and `<!-- HEADER -->` (line 386).

`dashboards/` at the repo root holds a byte-identical copy of all six exports (verified with `cmp` on
2026-09-03; it is the original Jul-16 drop, `docs/design/mockups/` the Aug-27 copy taken into the repo).
It is untracked and duplicates committed files — a drift hazard, recorded as carry-forward. Read
`docs/design/mockups/`, the path `schema.json` points at.

## Scope

The three regions this story owns, across all four persona dashboards. Everything else on those
mockups belongs to ARC-01/DEV-01/PMD-01/EMD-01.

| Region | Component | Mockup anchor |
|---|---|---|
| Brand bar + signed-in identity | `PersonaDashboardShell.tsx` (identity block inline, per D-01) | `<!-- BRAND BAR -->` |
| Persona tag + subtitle | `PersonaHeader.tsx` | `<!-- HEADER -->`, first child |
| Program context | `ProgramContext.tsx` | `<!-- HEADER -->`, second child |

Explicitly **not** in scope: EMD's `Switch program` dropdown (a sibling rendered after the shell by
EMD-01, research condition C-4).

## Tokens used

All values byte-exact from the decoded mockups. Per `DECISIONS.md` D-06, static values are literal rules
in each component's CSS Module; only the data-driven `{color, background}` pair crosses as a minimal
`React.CSSProperties` `style` prop.

### Persona colors — `docs/design/tokens.md` § Persona colors

| Persona key | Tag text | Subtitle text | Tag/avatar color | Tag background |
|---|---|---|---|---|
| `architect` | `Architect` | `Architect overview` | `#6a4fd0` | `#f0edfb` |
| `developer` | `Developer` | `Developer overview` | `#2a6fdb` | `#e9f1fd` |
| `product-manager` | `Product Manager` | `Product Manager overview` | `#d97757` | `#fdefe9` |
| `engineering-manager` | `Eng Manager` | `Engineering manager overview` | `#1f8a5b` | `#eaf6ef` |

The `engineering-manager` row carries two irregularities that are correct as written and are why the
four literals must never be templated (condition C-4): the tag is `Eng Manager`, not "Engineering
Manager", and the subtitle has a lowercase `m`. `formatPersonaTag.test.ts` asserts both byte-exact.

There is no `cio` row. The CIO Portfolio mockup has no persona tag/subtitle region at all, which is why
`cio` is an invariant violation that throws (`PersonaTagError`, FR-2/D-03), not a fifth branch.

### Program type colors — `docs/design/tokens.md` § Program type colors

| `program.type` | Color | Background | Avatar abbreviation |
|---|---|---|---|
| `Migration` | `#2a6fdb` | `#eaf1fc` | `M` |
| `Greenfield feature development` | `#1f8a5b` | `#e8f5ee` | `G` |
| `Brownfield feature development` | `#7c5cff` | `#efebff` | `B` |
| `Maintenance` | `#c08a1e` | `#fdf3e0` | `MT` |

Sourced from the EMD mockup's `tMap`, the only mockup that renders more than one program and therefore
the only one that shows the mapping. ARC/DEV/PMD hardcode `avatar: 'M'` and a fixed page `accent` of
`{c:'#2a6fdb', bg:'#eaf1fc'}` — indistinguishable from `Migration`'s pair, because their fixture program
*is* a Migration. D-04 generalised EMD's type-keyed map to all four pages; that is a deliberate
generalisation from one mockup, not something all four independently show.

The **Avatar abbreviation** column is currently unread by the code. See § Known divergences.

### Static values

| Element | Values |
|---|---|
| Brand bar | `padding:14px 34px` · `border-bottom:1px solid #eef0f3` · `background:#fff` · `gap:12px` |
| Logo tile | `32×32` · `border-radius:9px` · `background:#2a6fdb`; inner `13×13`, `border:2.4px solid #fff`, `border-radius:4px`, `rotate(45deg)` |
| Product name | `15px` / `800` / `letter-spacing:-.3px` — `AgentRise Harness` |
| Tagline | `10.5px` / `600` / `#8a93a1` / `letter-spacing:.2px` / `margin-top:1px` — `AI SDLC Governance` |
| Identity name | `13px` / `600` / `line-height:1.2` |
| Identity job title | `11px` / `500` / `#8a93a1` |
| Identity avatar | `34×34` · `border-radius:50%` · `13px` / `700` · white text on the persona color |
| Identity neutral fallback | `34×34` · `border-radius:50%` · `#e4e7ec` · no initials · `aria-hidden="true"` (D-05) |
| Header region | `padding:18px 34px 20px` · `border-bottom:1px solid #e9ebef` · `background:#ffffffcc` · `backdrop-filter:blur(8px)` · `position:sticky; top:0; z-index:5` |
| Persona line | `gap:8px` · `12.5px` / `600` / `#7a828f` · `margin-bottom:12px` |
| Tag pill | `11px` / `700` · `padding:3px 9px` · `border-radius:20px` |
| Program avatar tile | `52×52` · `border-radius:14px` · `19px` / `800` / `letter-spacing:-.5px` |
| Program name | `22px` / `800` / `letter-spacing:-.5px` |
| Type chip | `inline-flex` · `11px` / `700` · `padding:3px 10px` · `border-radius:20px` |
| Program description | `13px` / `500` / `#5b6472` · `line-height:1.45` · `margin-top:6px` · `max-width:760px` |
| Neutral error badge | tag-pill geometry · `#5b6472` on `#e4e7ec` · text `Persona unavailable` |

## Screens × form factors

| Screen | Source artifact | Desktop | Tablet | Mobile |
|---|---|---|---|---|
| Brand bar + identity | `docs/design/mockups/Architect Dashboard.html` § BRAND BAR (identical in all four) | specified | **not specified** | **not specified** |
| Persona tag + subtitle | same file § HEADER, first child | specified | **not specified** | **not specified** |
| Program context | same file § HEADER, second child (EMD binds `proj.*`, ARC/DEV/PMD `prog.*` — mockup drift, condition C-4) | specified | **not specified** | **not specified** |

**The mockups are desktop-only** (`docs/design/README.md`, `docs/design/tokens.md` § Responsive) while the
project's target platform is "Web (desktop + mobile responsive)" (`CLAUDE.md`). No breakpoints, no tablet
or mobile composition exists for any of these regions. SHP-01 therefore ships desktop-only by design
(PRD § Scope "Out": "Mobile/responsive layout — mockups are desktop-only; no mobile design exists yet for
this shell"), and the only responsive affordance carried over is the mockups' own `flex-wrap:wrap` plus
`min-width:220px` on the program block. Nothing was invented. Closing this gap needs a design decision,
not an implementation one.

## Design QA — contrast audit (PRD SHP-01-NFR-3)

PRD SHP-01-NFR-3 routes the "≥4.5:1 text contrast" verification for the persona pairs to "design QA in
`DESIGN.md`". This is that verification, run for the first time on 2026-09-03. Ratios computed with the
WCAG 2.2 relative-luminance formula. The bar is 4.5:1 for normal text and 3:1 for large text
(≥18.66px bold), applied per element's actual size.

| Element | Key | fg | bg | Ratio | Bar | |
|---|---|---|---|---|---|---|
| Persona tag pill | `architect` | `#6a4fd0` | `#f0edfb` | 5.00 | 4.5 | PASS |
| Persona tag pill | `developer` | `#2a6fdb` | `#e9f1fd` | **4.20** | 4.5 | **FAIL** |
| Persona tag pill | `product-manager` | `#d97757` | `#fdefe9` | **2.78** | 4.5 | **FAIL** |
| Persona tag pill | `engineering-manager` | `#1f8a5b` | `#eaf6ef` | **3.91** | 4.5 | **FAIL** |
| Neutral error badge | invalid persona | `#5b6472` | `#e4e7ec` | 4.83 | 4.5 | PASS |
| Identity avatar initials | `architect` | `#ffffff` | `#6a4fd0` | 5.77 | 4.5 | PASS |
| Identity avatar initials | `developer` | `#ffffff` | `#2a6fdb` | 4.78 | 4.5 | PASS |
| Identity avatar initials | `product-manager` | `#ffffff` | `#d97757` | **3.12** | 4.5 | **FAIL** |
| Identity avatar initials | `engineering-manager` | `#ffffff` | `#1f8a5b` | **4.33** | 4.5 | **FAIL** |
| Program type chip | `Migration` | `#2a6fdb` | `#eaf1fc` | **4.21** | 4.5 | **FAIL** |
| Program type chip | `Greenfield feature development` | `#1f8a5b` | `#e8f5ee` | **3.87** | 4.5 | **FAIL** |
| Program type chip | `Brownfield feature development` | `#7c5cff` | `#efebff` | **3.72** | 4.5 | **FAIL** |
| Program type chip | `Maintenance` | `#c08a1e` | `#fdf3e0` | **2.77** | 4.5 | **FAIL** |
| Program avatar tile (large) | `Migration` | `#2a6fdb` | `#eaf1fc` | 4.21 | 3.0 | PASS |
| Program avatar tile (large) | `Greenfield feature development` | `#1f8a5b` | `#e8f5ee` | 3.87 | 3.0 | PASS |
| Program avatar tile (large) | `Brownfield feature development` | `#7c5cff` | `#efebff` | 3.72 | 3.0 | PASS |
| Program avatar tile (large) | `Maintenance` | `#c08a1e` | `#fdf3e0` | **2.77** | 3.0 | **FAIL** |
| Persona subtitle text | all | `#7a828f` | `#ffffff` | **3.88** | 4.5 | **FAIL** |
| Brand tagline | static | `#8a93a1` | `#ffffff` | **3.10** | 4.5 | **FAIL** |
| Identity job title | static | `#8a93a1` | `#ffffff` | **3.10** | 4.5 | **FAIL** |
| Program description | static | `#5b6472` | `#ffffff` | 5.98 | 4.5 | PASS |

**13 of 22 pairs fail.** Every failing value is the mockups' own — the implementation reproduced them
byte-exactly, so this is an inherited design defect, not an implementation defect, and no code change
here would fix it without diverging from the authoritative design.

What this means concretely:

- **3 of the 4 persona tag pills fail** — exactly the check the PRD asked for. Only `architect` passes.
- **All 4 program type chips fail** at 11px. The same pairs pass comfortably as the 19px/800 avatar tile,
  so the colours are usable at large sizes and not at chip size.
- **The two neutral greys `#8a93a1` and `#7a828f` fail on white**, which is not an SHP-01 problem: they
  are global text tokens (`docs/design/tokens.md`) used by the tagline, job title and persona subtitle,
  and every future UI story that reads them inherits the same failure.
- The neutral error badge and the identity-avatar initials for `architect`/`developer` pass.

**Not resolved here, deliberately.** `CLAUDE.md` makes the mockups authoritative and says to raise, not
design, anything they do not settle; darkening these tokens is a design decision with blast radius across
every dashboard, not an implement-phase edit. The story's own NFR softens the bar to "WCAG AA, where
feasible" (story NFR-008, carried verbatim into PRD SHP-01-NFR-3), so shipping these values is a
*documented, now-evidenced* deviation rather than an unknown. Carried forward for a design decision.

## Implementation notes for /arh-implement

Recorded after the fact; these are the bindings the shipped code actually makes.

- **Prop contract**: `docs/requirements/api.md#persona-shell`. `{ signedInUser?, persona?, program }`.
  Data only — no CSS strings on the wire (FR-4, condition C-5), declining the mockups' own
  style-binding precedent (`docs/design/README.md` § "The templates also bind presentation").
- **Loading gate**: `persona === undefined` is the *only* gate. While loading, only the brand bar's left
  half renders — no identity block, no tag, no subtitle, no program context, and no skeleton (FR-5,
  NFR-2 flash prevention).
- **Error state**: any `persona` outside the four valid keys — including `cio` and any resolver-error
  sentinel — renders the neutral `Persona unavailable` badge, no subtitle, plus a visually-hidden
  `aria-live="assertive"` region reading `Unable to load your dashboard view.` (D-03). Visually-hidden is
  implemented as a clip-rect utility, never `display:none` (which screen readers skip).
- **Colour agreement**: the identity avatar's background and the tag pill's text colour are the same
  `formatPersonaTag(persona).color` value, so they cannot disagree (D-02).
- **Fail-loud vs fail-soft**: `formatPersonaTag()` throws on an unknown persona (a shell-owned invariant,
  FR-2); `getProgramStyle()` falls back to `Migration` on an unknown type (caller-resolved data,
  condition C-3, mirroring the mockup's own `tMap[ptype] || tMap['Migration']`). The asymmetry is
  intentional.
- **No consumer yet**: ARC-01/DEV-01/PMD-01/EMD-01 are the named consumers and are not yet planned.
  Do not add a page/route/demo to wire this up (PRD § Scope).

## Known divergences from the mockups

| # | Divergence | Status |
|---|---|---|
| 1 | `program.icon` is a free-form caller-supplied field; the mockups derive the avatar glyph from `program.type` (EMD `avatar: tMap[ptype].ab`). `tokens.md`'s Avatar abbreviation column is unread. | `REVIEW.md` F-1 (HIGH), carried forward as `SHP-01-icon-field-mockup-mismatch`. Decided: carry, not fix — dropping `icon` amends an approved PRD (FR-4) and a certified story. |
| 2 | Program avatar/chip colours are type-keyed on all four pages; ARC/DEV/PMD actually use a fixed page `accent`. | Deliberate (D-04). Indistinguishable in the mockups' own fixture data, and type-keying is what makes the four pages consistent. |
| 3 | Inline styles re-expressed as CSS Modules. | Deliberate (D-06); this repo has no CSS framework and `next-patterns` records CSS Modules as the convention. Values preserved, mechanism replaced. |
| 4 | Desktop-only; no tablet/mobile composition. | Inherited from the mockups. See § Screens × form factors. |
| 5 | 13 of 22 colour pairs below their WCAG bar. | Inherited from the mockups. See § Design QA. |
