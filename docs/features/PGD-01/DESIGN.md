# DESIGN: PGD-01 — Program Detail page shell

**Provenance**: hand-authored 2026-09-03 during `/arh-plan-requirements` Phase 2. `ux-agent` is not
installed in this repo (same gap SHP-01 hit — see `docs/features/SHP-01/DESIGN.md`), so this file was
written directly from the authoritative design source instead of generated. Unlike SHP-01's, this one is a
**pre-implementation spec**: no code exists yet for these regions. The mockup, not this file, is the source
of truth on any disagreement.

**Design source**: `docs/design/mockups/Program Detail.html` (`docs/design/schema.json` → PGD epic). A
Claude Design canvas export — it must be decoded before the markup is readable; see `docs/design/README.md`
for the procedure. Line references below are into the decoded document.

## Scope

The four regions this story owns. Everything else on the same mockup belongs to PGD-02..06.

| Region | Component | Mockup anchor |
|---|---|---|
| Back-to-board link | `BackToProgramBoard.tsx` | `<!-- HEADER -->` L389, first child |
| Program header | `ProgramDetailHeader.tsx` | `<!-- HEADER -->` L390–408 |
| Switch-program selector | `ProgramSwitcher.tsx` | `<!-- HEADER -->` L400–418 |
| 7 summary cards | `ProgramSummaryCards.tsx` | `<!-- PROJECT SUMMARY -->` L427–446 |

Explicitly **not** in scope, though the same mockup renders them below the cards: Daily Token Consumption
(PGD-02), Releases (PGD-03), Commands (PGD-04), Team (PGD-05), session chart (PGD-06).

## Region 1 — Back-to-board link

```
← Back to program board
```

Inline-flex anchor, `gap:6px`, `12.5px/600`, `#7a828f`, no underline, `margin-bottom:12px`; hover
`#2a6fdb`. The glyph `←` is part of the label string, not a separate icon element.

**Binding gap**: the mockup's target is `href="CIO Portfolio Dashboard.html"` — a canvas-relative file, not
a route. The Adoption Overview route is owned by the OVW epic and is not yet built, so PGD-01 cannot read a
real target off the mockup. Resolve when OVW-01 lands; until then the link target is the one value in this
file not settled by the design source.

## Region 2 — Program header

Row: `display:flex; align-items:center; gap:16px; flex-wrap:wrap`, inside a sticky header
(`padding:18px 34px 20px`, `border-bottom:1px solid #e9ebef`, `background:#ffffffcc`,
`backdrop-filter:blur(8px)`, `position:sticky; top:0; z-index:5`).

| Element | Binding | Style |
|---|---|---|
| Avatar | `{{ prog.avatar }}` in a `{{ prog.avatarStyle }}` box | Both pre-formatted server-side — the style string ships as data, per README § "templates bind CSS as well as data" |
| Name | `{{ prog.name }}` | `22px/800`, `letter-spacing:-.5px` |
| Type chip | `{{ prog.ptype }}` in `{{ prog.typeChip }}` | Chip CSS is a pre-formatted binding, not a class |
| Description | `{{ prog.scope }}` | `13px/500`, `#5b6472`, `line-height:1.45`, `max-width:760px` |

Name / chip row is its own flex line (`gap:11px; flex-wrap:wrap`); the description sits below it
(`margin-top:6px`). The text column is `flex:1; min-width:220px`.

**Design gap — the persona chip.** L396 renders a *static* `CIO / CXO` chip
(`11px/700`, `#0f1a2e` on `#e6e9ef`, `padding:3px 9px`, `border-radius:20px`) as a sibling of the type chip.
It is hardcoded in the mockup, not a binding. PGD-01 must not render it from the detail response: AC-6
requires byte-identical payloads across personas and forbids persona branching in this endpoint. Persona
display is SHP-01's `PersonaHeader` concern. Flagged for the gate — either the chip is the persona shell
bleeding into the PGD mockup, or it is a genuine header element that needs a persona source PGD-01 does not
have. Do not invent one.

## Region 3 — Switch-program selector

Labelled `Switch program` (`10.5px/700`, `#a2abb8`, uppercase, `letter-spacing:.5px`), column layout
`gap:6px`, `align-self:flex-start`, control `min-width:240px`.

**Button** — full width, `gap:10px`, white, `1px solid {{ progBorder }}`, `border-radius:10px`,
`padding:9px 14px`, `13.5px/700`. Contents: `{{ prog.dotStyle }}` swatch, `{{ prog.name }}` (ellipsis-
truncated), caret `▾` rotated by `{{ caretTf }}`. Open/close via `{{ toggleProg }}`; `progBorder` and
`caretTf` are open-state-derived, so they are client state, not payload.

**Menu** — `sc-if` on `{{ progOpen }}` (default closed). Absolute, `top:calc(100% + 6px)`, white,
`1px solid #e4e7ec`, `border-radius:12px`, `box-shadow:0 12px 30px rgba(15,26,46,.14)`, `padding:5px`,
`z-index:30`.

**Rows** — `sc-for` over `{{ progOptions }}` with `hint-placeholder-count="6"`, each an `<a>`:

| Binding | Source |
|---|---|
| `o.href` | AUTH-04 `programs-api` — **see the blocker below** |
| `o.dotStyle` | AUTH-04, pre-formatted CSS |
| `o.label` | AUTH-04 |
| `o.rowStyle` | Client-derived (weight/background differ for the current row) |
| `o.current` | Client-derived — `sc-if`-gated `✓` in `#2a6fdb`, `13px/800` |

`rowStyle` and `o.current` are the deliberate exception to "values arrive pre-formatted" (ADR-0005 §2):
they describe the row's relationship to the current route, which only the client knows.

**Blocker (research Risk #9 / CF-05).** The mockup binds `o.href` straight into the anchor, and the
mockup's own data builds it as a page target (`'Program Detail.dc.html?p=' + k`). Shipped AUTH-04 emits
`/api/overview/program-detail/{program_id}` — the JSON API path
(`services/api/app/api/programs.py:132`). Bound as designed, a click lands the browser on raw JSON and
ADR-0005 §2's active-row comparison never matches. Fix in AUTH-04 under its own PR (`/programs/{program_id}`)
before this component is built.

## Region 4 — Program summary cards

Section heading: `8px` square dot `#2a6fdb` (`border-radius:2px`), `Program summary` (`14px/700`,
`letter-spacing:-.2px`), then `— to date` (`12px/500`, `#9aa2ae`). The "to date" qualifier is static
copy, not a computed range — there is no range toggle on this section and no as-of timestamp anywhere in
the mockup (research Risk #3).

Grid: `repeat(auto-fit, minmax(200px, 1fr))`, `gap:16px`. `sc-for` over `{{ summary }}` with
`hint-placeholder-count="7"` — the 7 is the contract, not a sample size.

Card: white, `1px solid #e6e9ef`, `border-radius:16px`, `padding:18px 19px`, column `gap:16px`,
`box-shadow:0 1px 2px rgba(15,26,46,.04)`. Glyph tile `38×38`, `border-radius:11px`, `#eef3fb`,
`#2a6fdb`, `15px/800`, **`'JetBrains Mono', monospace`** — the one place in this story that leaves the
body font. Value `25px/800`, `letter-spacing:-.8px`, `line-height:1`, `#0f1a2e`. Label `12px/500`,
`#7a828f`, `margin-top:7px`.

The 7 cards, in mockup order — order is part of the contract:

| # | Glyph | Label | Value source |
|---|---|---|---|
| 1 | `⬡` | Token consumption | `format_number()` |
| 2 | `✦` | Features delivered via Harness | `format_number()` |
| 3 | `⤴` | Releases done via Harness | `format_number()` |
| 4 | `❯` | Repos with Harness installed | `"{repos} / {repos_total}"` — a ratio string, **not** `format_number()` |
| 5 | `›_` | Commands executed | `format_number()` |
| 6 | `</>` | Lines of code generated | `format_number()` |
| 7 | `≡` | User stories delivered | `format_number()` |

Glyphs are literal characters in the markup, not an icon set. Card 4 is the one non-magnitude value, which
is why PRD FR-2 exempts it from the formatter.

## States

| State | Source in the mockup | Render |
|---|---|---|
| Populated | Default | As specified above |
| Loading | `hint-placeholder-count` on both `sc-for` blocks (7 cards, 6 switcher rows) | Placeholder rows at those counts — the mockup gives no skeleton treatment, so match the populated geometry and suppress text |
| Switcher closed | `sc-if value="{{ progOpen }}" hint-placeholder-val="{{ false }}"` | Default; menu absent from the DOM, not merely hidden |
| Error (404) | Not in the mockup | Story AC-7 requires an error state rather than a blank shell. The mockup shows no error treatment, so this is the second value not settled by the design source — decide at implementation, do not invent a screen here |

Desktop-only, per `docs/design/README.md` — these exports carry no breakpoints despite the responsive
target. The card grid's `auto-fit`/`minmax` reflows on its own; nothing else in these four regions does.

## Tokens

All values above are byte-exact from the decoded mockup, quoted inline as literal rules rather than
abstracted — consistent with SHP-01 D-06. Cross-reference `docs/design/tokens.md`; where this file and
tokens.md disagree, the decoded mockup wins and tokens.md should be corrected.

## Open design items for the gate

1. Persona chip (`CIO / CXO`, L396) — static in the mockup, conflicts with AC-6's no-persona-branching rule.
2. Back-to-board target — depends on the unbuilt OVW route.
3. 404 error state — required by AC-7, absent from the mockup.

None is a reason to hold the PRD; all three need a decision before the components are built.
