# DESIGN — PGD-05 Project team table + per-member usage popup

**Provider**: `html-mockup` · **Source**: `docs/design/mockups/Program Detail.html` (PGD epic, per `docs/design/schema.json`), `<!-- TEAM -->` section
**Iteration**: 1 · **Status**: Screen 1 extracted from the authored mockup (unchanged since iteration 0);
Screen 2 **originated** under `REQUIREMENTS.md` § Constraints' design gate — no mockup backs it

The mockup is authored, not generated here. It is a bundler output — see `docs/design/README.md`
for the decode snippet before diffing or grepping.

PGD-05 ships **both** halves (PRD § Scope): the endpoint *and* the team-table UI plus popup
wiring. Screen 1 below is fully specified by the PGD mockup and is **shipped and implemented —
unchanged by this iteration**. **Screen 2 is in no mockup at all**; it is originated design,
authored this round under the design gate `REQUIREMENTS.md` § Constraints names. Read its
provenance block before building from it.

## Screen 1: Project team panel

Embedded section on the existing Program Detail page. No route of its own. **Right** card of the
`COMMANDS + TEAM` two-up section (`repeat(auto-fit,minmax(min(100%,360px),1fr))`, `gap:16px`),
below the releases list (PGD-03); the left card is Commands executed (PGD-04, `DESIGN.md`).

### Container

`background:#fff · border:1px solid #e9ebef · border-radius:16px · overflow:hidden`
Header block `padding:18px 22px 14px` with `border-bottom:1px solid #f0f1f4`. Unlike PGD-04's
`20px` gutter, this panel's horizontal padding is `22px` throughout (header, column head, rows) —
the two sibling cards are deliberately not identical here.

### Header

| Element | Spec | Binding |
|---|---|---|
| Title | `15px/700`, `letter-spacing:-.2px` | literal `Project team` |
| Subtitle | `12.5px/500`, `#7a828f`, `margin-top:3px` | `Members & contribution · {{ teamRangeLabel }}` |
| Range chips | `sc-for {{ teamRanges }}` (`hint-placeholder-count="3"`), pill group `background:#eef0f3 · border-radius:10px · padding:3px · flex:none` | `{{ r.label }}`, `{{ r.style }}` |

`teamRangeLabel` is a fixed map, mockup L762 — `7d → "last 7 days"`, `30d → "last 30 days"`,
`90d → "last 90 days"`. Chip labels are `7D` / `30D` / `90D`; the active chip is
`background:#fff · color:#151a22 · box-shadow:0 1px 2px rgba(0,0,0,.08)`, inactive is transparent
`#7a828f` (`segBtn()`). Range state and chip styling are client-owned — the API supplies neither.

There is **no total/aggregate value** in this header, unlike PGD-04's `{{ cmdTotal }}` block. The
panel shows rows only.

### Column head row

`display:grid · grid-template-columns:1.8fr 1fr 1fr 1fr 1fr · padding:11px 22px`,
`background:#fafbfc`, `border-bottom:1px solid #f0f1f4`,
`10.8px/700 · letter-spacing:.5px · color:#a2abb8 · text-transform:uppercase`.

| Column | Literal | Align | Grid track |
|---|---|---|---|
| 1 | `Member` | left | `1.8fr` |
| 2 | `Role` | left | `1fr` |
| 3 | `Sessions` | right | `1fr` |
| 4 | `Tokens` | right | `1fr` |
| 5 | `Avg / session` | right | `1fr` |

Column order is the contract and matches `ProgramTeamRow`'s locked field order
(PGD-05-FR-2: `member_name`, `role`, `sessions`, `tokens`, `avg_tokens_per_session`).

### Row list

`<sc-for list="{{ people }}" as="p" hint-placeholder-count="7">`. Each row is the **same
5-column grid** as the head, `padding:13px 22px`, `align-items:center`,
`border-bottom:1px solid #f4f5f7`:

| Element | Spec | Binding |
|---|---|---|
| Avatar circle | `30×30 · border-radius:50% · color:#fff · 11px/700 · flex:none`, centred | `{{ p.avBg }}` (background), `{{ p.initials }}` |
| Member name | `13.5px/600`, `white-space:nowrap` + ellipsis overflow, in a `flex · gap:11px · min-width:0` cell with the avatar | `{{ p.name }}` |
| Role | `12.5px/500`, `#5b6472` | `{{ p.role }}` |
| Sessions | `13px/600`, right-aligned, default font | `{{ p.sessions }}` |
| Tokens | `13px/600`, right-aligned, **JetBrains Mono** | `{{ p.tokens }}` |
| Avg / session | `13.5px/700`, right-aligned, **JetBrains Mono** | `{{ p.avg }}` |

Note the deliberate typographic split: `Sessions` uses the body face, `Tokens` and
`Avg / session` use JetBrains Mono, and `Avg / session` is one step heavier (`700` vs `600`) and
larger (`13.5px` vs `13px`) than its two neighbours. It is the emphasised column.

Ordering is descending by contribution (the mockup's `pool` weights are authored 0.20 → 0.08),
matching PGD-05-FR-2's "rows ordered descending by `tokens`".

### Avatar colour and initials — not supplied by this story's API

`p.avBg` and `p.initials` are consumed by the row but are **absent from `ProgramTeamRow`**
(PGD-05-FR-2 locks five fields, "no additional fields"). The mockup's generator hardcodes both
per person (L766–772). Two values are therefore renderer-owned, derived client-side from
`member_name` + `role`:

- **`initials`** — derived from `member_name` client-side. The mockup supplies no derivation
  rule; two-letter first+last initial is what every sample shows (`Devon Rao → DR`).
- **`avBg`** — the mockup's per-person colours are **exactly** `docs/design/tokens.md`
  § Persona colors, keyed by `role`: `Architect → #6a4fd0`, `Developer → #2a6fdb`,
  `Product Manager → #d97757`, `Eng Manager → #1f8a5b`. **`QA Engineer → #d1495b` is the
  exception: that hex appears in this mockup and in no token table.** A renderer must either add
  it as a token or raise it — do not silently pick a near colour.

This is a divergence from the PGD-04 precedent, where `barStyle` arrives pre-built in the
response. Here the CSS-bearing value (`avBg`) is **not** in the response and the frontend must
own the map. If a future story prefers server-supplied avatar styling, that is a schema change to
`ProgramTeamRow`, not something to smuggle in.

### Pre-formatted values

Per `docs/design/README.md` § "Values arrive pre-formatted", the panel formats nothing. The
mockup's generator (L774–783) emits every cell as a **string**:

| Mockup binding | Generator output | Example |
|---|---|---|
| `p.sessions` | `String(sessions)` | `"22"` |
| `p.tokens` | `fmtM(tok)` — `≥1000 → "x.xxB"`, else `"x.xM"` (L684) | `"4.2M"` |
| `p.avg` | `Math.round(avgK) + 'K'` | `"191K"` |

**This is the story's one live contract conflict.** PGD-05-FR-2 locks `sessions: int`,
`tokens: int`, `avg_tokens_per_session: int` — raw ints — while the mockup renders
pre-formatted magnitude strings. Both positions already exist in this codebase: PGD-02's
token-trend returns raw ints and the frontend formats; PGD-03's releases returns pre-formatted
strings. PGD-05-FR-2 chose raw ints, so **the renderer owns `M`/`K`/`B` formatting for all three
numeric columns**, mirroring PGD-02. Recorded here so a later reader does not read the mockup
literally and "fix" the API to return strings.

### Empty / placeholder state

`hint-placeholder-count="7"` renders seven placeholder rows in the canvas; the generator's `pool`
has exactly seven entries. That is a canvas rendering hint, **not** a contract that the API
returns seven rows — no minimum or maximum row count is specified.

The mockup shows **no empty-state copy, no loading state, and no error state**. PRD § Screen
inventory lists Loading / Empty / Error for this panel and the story's decision log (b) settles
"zero active members → empty list, not an error" at the API level — but the *rendering* of that
empty list is undesigned: the header and column-head row would render over nothing. Empty-,
loading- and error-state copy must be raised before a renderer ships it, not invented.

### Sample names are never shipped

`Devon Rao`, `Maya Chen`, `Noah Kim`, `Aisha Bello` and the rest are placeholders per
`docs/design/README.md` § Recorded divergences — never shipped, not even as fallback copy. An
unresolved `member_name` renders a neutral state.

## Screen 2: Member usage popup — ORIGINATED, NOT EXTRACTED

> **Provenance.** **No mockup in `docs/design/mockups/` contains this popup.** Iteration 0's finding
> stands and was re-verified this round: `Program Detail.html` has no modal, overlay, or dialog of
> any kind, and its team rows carry neither `sc-camel-on-click` nor `cursor:pointer`. This section
> is therefore **originated design**, authored under the explicit design gate
> `REQUIREMENTS.md` § Constraints names (`/arh-iterate-design PGD-05`), not extracted from a canvas
> export. It is assembled from three established sources, each cited inline below:
>
> | Layer | Source | Status |
> |---|---|---|
> | Modal **chrome** (overlay, panel, header, close, range chips, scroll container) | `Engineering Manager Dashboard.html` § `<!-- MEMBER COMMAND POPUP -->` (EMD epic) | Real mockup markup, **different epic** — reused as house pattern |
> | **Content** (4 cards · daily-tokens chart · commands list) | `Architect Dashboard.html` §§ `<!-- MY USAGE -->`, `<!-- YOUR DAILY TOKEN CONSUMPTION -->`, `<!-- YOUR COMMANDS -->` (ARC epic), and the shipped `ProgramSummaryCards` / `DailyTokenTrendChart` components | Real mockup markup + shipped code — the ARC sections render the **same `personal-usage-api` contract** this popup renders |
> | Every colour, size, radius, shadow, spacing | `docs/design/tokens.md` | Tokens only — no invented values (one gap flagged in § Token gaps) |
>
> **Interaction states not present in any of those sources** — focus-visible, focus trap, Esc/overlay
> dismissal, and the Loading / Denied / Error states — are **newly authored here**. They are marked
> **[NEW]** wherever they appear.
>
> A future canvas export of this popup **supersedes this section entirely**. When one lands, re-extract
> and record any delta in `docs/design/README.md` § Recorded divergences rather than keeping this text.

### Why the EMD popup is chrome-only and not a content model

`Engineering Manager Dashboard.html`'s popup renders a **command list only** — a `total runs` figure
and an `sc-for` of command/count/bar rows. PGD-05 AC-10 requires `personal-usage-api`'s response
**verbatim**: `{cards, daily_tokens, commands}`. The EMD popup has one of those three blocks and its
`total runs` header has no counterpart in the SHP-02 envelope. **Its content shape is therefore not
copied.** Its *chrome* is, because it is the only modal the design system has and it exists for
exactly this interaction (click a team row → see that member's data).

The content shape instead follows the ARC/DEV/PMD mockups' `MY USAGE` + `YOUR DAILY TOKEN
CONSUMPTION` + `YOUR COMMANDS` sections, which bind `myKpis` / `tokChart` / `commands` — the same
three blocks, from the same contract (`docs/requirements/api.md#personal-usage-api`,
`services/api/app/schemas/personal_usage.py`). Those sections are full-page, not modal; this design
is their content at modal scale.

---

### 2.1 The row trigger (on Screen 1's team table) — **[NEW]**, EMD precedent

Screen 1's shipped row is **not** interactive today: no click handler, no `cursor:pointer`, no focus
treatment. T-16 must add the following. Screen 1's *visual* row spec (§ Row list) is otherwise
unchanged — this adds interaction only, no layout or typography change.

**Element.** Each team row becomes a `<button type="button">` spanning the full row, with
`display:grid` carrying the existing `1.8fr 1fr 1fr 1fr 1fr` template, `width:100%`, `text-align` per
cell as today, `background:transparent`, `border:none`, `border-bottom:1px solid #f4f5f7`,
`padding:13px 22px`, `font:inherit`. A native `<button>` rather than `<div role="button">` — it gets
Enter/Space activation, focus order, and the accessible-name computation for free (NFR-008).

| State | Spec | Source |
|---|---|---|
| Rest | unchanged from § Row list | Screen 1 |
| Hover | `background:#f7f9fb` · `cursor:pointer` | **EMD row, verbatim** (`style-hover="background:#f7f9fb"`, `cursor:pointer`) |
| Focus-visible | `outline:2px solid #2a6fdb` (Primary/brand token) · `outline-offset:-2px` · `border-radius:8px` (controls radius) | **[NEW]** — no mockup shows a focus ring anywhere |
| Pressed / active | `background:#f2f4f7` (Border and surface ramp) | **[NEW]** |
| Open (this row's popup is showing) | `background:#f7f9fb` retained while open, `aria-expanded` is **not** used (a dialog is not a disclosure); the row instead carries `aria-haspopup="dialog"` | **[NEW]** |

`outline-offset:-2px` keeps the ring inside the row so it never overlaps the adjacent row's
`1px` divider.

**Accessible name.** The row's flat text content (`"Devon Rao QA Engineer 22 4.2M 191K"`) is a poor
name. T-16 must supply an explicit one:

```
aria-label = `View usage for ${member_name}, ${role}`
```

The numeric cells stay in the row's visible content (they are the table data) but are excluded from
the name by the explicit `aria-label`. `member_name` renders `docs/design/README.md` § Recorded
divergences' neutral state when unresolved — in that case the label degrades to
`View usage for this member` rather than embedding a placeholder name.

**Keyboard operability (NFR-008 / WCAG 2.1 AA).** Tab reaches every row in DOM order (descending by
tokens, § Row list). Enter and Space open the popup — native `<button>` behaviour, no key handler to
write. No roving tabindex: the row count is unbounded but small, and a full tab stop per row is the
honest affordance for "each row opens a different thing".

**Touch.** The row's `13px 22px` padding yields a ~56px tall target, already above the 44px guideline
— unlike the range chips, which needed `DailyTokenTrendChart.module.css`'s `@media (pointer:coarse)`
growth. No coarse-pointer override is required here.

---

### 2.2 Modal chrome — reused from EMD, with the deltas named

#### Reused from EMD verbatim

| Property | Value | Token |
|---|---|---|
| Overlay | `position:fixed · inset:0 · background:rgba(15,26,46,.42) · backdrop-filter:blur(2px) · z-index:60` | `rgba(15,26,46,…)` is the Ink token `#0f1a2e` at 42% |
| Overlay layout | `display:flex · align-items:center · justify-content:center · padding:24px` | Content padding `24px` |
| Panel | `background:#fff · border-radius:18px · box-shadow:0 24px 60px rgba(15,26,46,.28) · overflow:hidden` | see § Token gaps — `18px` and this shadow are both off-token |
| Header block | `padding:20px 22px · border-bottom:1px solid #f0f1f4 · display:flex · align-items:center · gap:13px` | `#f0f1f4` border ramp |
| Header avatar | `44×44 · border-radius:50% · background:{avBg} · color:#fff · 15px/700 · flex:none`, centred | `50%` avatar radius; `avBg` per § 2.3 |
| Header name | `17px/800 · letter-spacing:-.3px` | `17px` type scale |
| Header sub-line | `12.5px/500 · #7a828f · margin-top:2px` | `12.5px`, text ramp |
| Close button | `32×32 · border-radius:9px · border:1px solid #e4e7ec · background:#fff · color:#7a828f · font-size:16px · cursor:pointer`, `style-hover:background:#f4f6f9` | `9px` radius, `#e4e7ec` border ramp; hover `#f4f6f9` is off-token — see § Token gaps |
| Range chip group | `display:flex · background:#eef0f3 · border-radius:10px · padding:3px · flex:none`, buttons per `segBtn()` (`12px/700 · padding:6px 13px · radius:8px`; active `background:#fff · color:#151a22 · box-shadow:0 1px 2px rgba(0,0,0,.08)`; inactive transparent `#7a828f`) | identical to the shipped `DailyTokenTrendChart.module.css` `.toggleTrack`/`.toggleButton` |
| Scroll container | `max-height:340px · overflow:auto` on the body region | EMD verbatim |

#### Changed from EMD, and why

| Change | EMD | Here | Reason |
|---|---|---|---|
| Panel `max-width` | `520px` | **`760px`** | EMD's body is a single-column command list. This popup carries a **4-card row** (`repeat(auto-fit,minmax(200px,1fr))` per `ProgramSummaryCards.module.css`) plus a chart. At `520px` the card grid collapses to 2×2 and the chart is unreadably narrow. `760px` fits four 200px-minimum cards inside `22px` gutters with the `16px` grid gap (`4×200 + 3×16 + 2×22 = 892` at minimum ideal — so the grid legitimately wraps to 2×2 at this width; see § 2.3 Cards, which accepts 2×2 as the shipped arrangement and keeps the chart full-width). `760px` is the width at which the chart is legible and the cards read as a block, not the width at which they fit on one line. |
| Header sub-line copy | `{{ popup.role }} · commands executed` | **`{role} · usage · {rangeLabel}`** | Content is no longer commands-only. `rangeLabel` is § Screen 1's fixed map (`7d → "last 7 days"` etc.), reused. |
| Header right-side figure | `{{ popup.total }}` + `total runs · {{ memRangeLabel }}` block above the list | **removed** | No counterpart in `PersonalUsageResponse`. The cards row carries the summary figures instead. |
| Range chip placement | In a dedicated strip *below* the header, sharing a row with the `total runs` figure | **moved into the header row**, right of the name block and left of the close button, `gap:12px` | With the `total runs` figure gone, the strip would hold nothing but the chips. Folding them into the header removes a near-empty row. |
| Body scroll region scope | Wraps the command list only | **Wraps the entire body** (cards + chart + commands), `padding:16px 22px 20px` | The body is now three blocks, not one; scrolling only the last would strand the chart. |
| Panel height | Unconstrained above `max-height:340px` on the list | **`max-height:min(78vh, 760px)`** on the panel, with the body region `flex:1 · overflow:auto · overscroll-behavior:contain` **[NEW]** | `340px` is far too short for three blocks. Bounding the panel rather than the list keeps the header and close button pinned while the content scrolls. `overscroll-behavior:contain` stops the page behind from scrolling at the ends. |

#### Dialog semantics — **[NEW]** (no mockup models any of this)

| Concern | Spec |
|---|---|
| Role | Panel carries `role="dialog"` + `aria-modal="true"` |
| Labelling | `aria-labelledby` → the header name element's id. Name is `{member_name}` — the visible heading, so no hidden-label divergence. Header name is an `<h2>` styled to the `17px/800` spec (not a bare `div`), so the dialog has a real heading. |
| Description | `aria-describedby` → the header sub-line id (`{role} · usage · {rangeLabel}`) |
| Initial focus | **The close button.** Not the panel, not the first range chip. It is the one control every state has (Populated / Loading / Denied / Error all render it), so initial focus never depends on which state rendered — and Esc-equivalent is one Enter away for a keyboard user. |
| Focus trap | Tab/Shift-Tab cycle within the panel only. Trap boundary is the panel element, not the overlay. |
| Focus restore | On dismiss, focus returns to **the row button that opened it** — required, not optional; without it a keyboard user lands at document start and must re-traverse the table. |
| Dismiss — Esc | Closes. Bound on the panel (the trap guarantees focus is inside). |
| Dismiss — overlay click | Closes. EMD's own pattern: `sc-camel-on-click="{{ closeMember }}"` on the overlay, with `sc-camel-on-click="{{ popup.stop }}"` on the panel to stop propagation. Reused verbatim. |
| Dismiss — close button | Closes. `aria-label="Close usage for {member_name}"` — **[NEW]**; EMD's `✕` glyph has no accessible name at all. Glyph stays `✕`, `aria-hidden` on the glyph itself. |
| Background inertness | `inert` on the page root while open (or `aria-hidden="true"` + focus trap where `inert` is unavailable), and `overflow:hidden` on `<body>` to prevent background scroll |
| Mount | Rendered in a portal at `<body>` level so the overlay's `z-index:60` is not trapped by the Program Detail page's stacking contexts (the sticky header is `z-index:5`, so `60` clears it) |

---

### 2.3 Populated state

Body region, top to bottom, `padding:16px 22px 20px`, block gap `20px`.

#### Block 1 — Cards row (`cards`, exactly 4)

Reuses the visual language of the shipped `ProgramSummaryCards.module.css` `.card`/`.glyph`/`.value`/
`.label`, with the **5-key** `PersonalUsageCard` shape (`glyph`, `value`, `label`, `iconBg`,
`iconColor`) rather than the 3-key `ProgramSummaryCard`:

| Element | Spec | Binding |
|---|---|---|
| Grid | `display:grid · grid-template-columns:repeat(auto-fit,minmax(200px,1fr)) · gap:16px` | — |
| Card | `background:#fff · border:1px solid #e6e9ef · border-radius:16px · padding:18px 19px · box-shadow:0 1px 2px rgba(15,26,46,.04) · display:flex · flex-direction:column · gap:14px` | Card recipe token, verbatim |
| Icon tile | `38×38 · border-radius:11px · background:{iconBg} · color:{iconColor} · 15px/800 · JetBrains Mono`, centred | `cards[i].iconBg`, `cards[i].iconColor`, `cards[i].glyph` |
| Value | `25px/800 · letter-spacing:-.8px · line-height:1 · color:#0f1a2e` | `cards[i].value` |
| Label | `12.5px/500 · #7a828f · margin-top:7px` | `cards[i].label` |

Two deliberate notes:

- **`iconBg`/`iconColor` come from the API**, unlike Screen 1's `avBg` which the renderer owns. This
  is the ADR-0009 contract (`PersonalUsageCard` carries both as pre-formatted CSS). The popup binds
  them; it does not consult `tokens.md` for them.
- **Value size is `25px`, not the ARC mockup's `27px`.** `tokens.md` § Typography records `25px` as
  the KPI-value token and the shipped `ProgramSummaryCards.module.css` `.value` uses `25px`.
  The ARC mockup's literal `27px` is untokenised; matching the shipped component is the consistent
  choice. Recorded so a later literal diff reads a decision, not drift.
- At `760px` panel width minus `44px` gutters, the `minmax(200px,1fr)` grid lands **2×2**, not 1×4.
  Accepted: the card block reads as a unit either way, and widening the panel far enough for 1×4
  (≈940px) would dominate the viewport. **Card order is still the contract** (Sessions, Total time,
  Total tokens, Avg tokens/session) and reading order stays row-major.

#### Block 2 — Daily tokens chart (`daily_tokens`)

Reuses `DailyTokenTrendChart`'s visual language at modal scale. Card shell per
`DailyTokenTrendChart.module.css` `.section` (`background:#fff · border:1px solid #e9ebef ·
border-radius:16px · padding:22px 24px 16px`).

| Element | Spec | Binding |
|---|---|---|
| Title | `15px/700 · letter-spacing:-.2px` | literal `Daily token consumption` |
| Subtitle | `12.5px/500 · #7a828f · margin-top:3px` | `AI token usage per day · {rangeLabel}` |
| Stat block (right) | total `20px/800 · letter-spacing:-.5px`; caption `10.5px/600 · #a2abb8 · uppercase · letter-spacing:.4px` | `daily_tokens.period_total` + `total · {daily_tokens.avg_per_day} / day avg` |
| Plot | The shipped SVG geometry, **re-proportioned**: `viewBox` stays `0 0 1000 240` with `preserveAspectRatio` so it scales into the narrower panel; rendered height `180px` rather than `240px` | `daily_tokens.points[].value` |

The range chips are **not** repeated here — the popup has one range control, in the header, governing
all three blocks. This is a deliberate divergence from the ARC mockup, where each section carries its
own chips: within a modal, three independent range controls over one member's data is noise, and the
contract fetches all three blocks from one ranged request.

**Empty series.** `points[]` is zero-padded by contract, so a member with no activity yields a
full-length all-zero series — a flat line at the axis floor, not a missing chart. The shipped
component's `MIN_AXIS_MAX` guard already covers the divide-by-zero. No separate "no chart data"
state exists or is needed.

#### Block 3 — Commands list (`commands`)

Card shell `background:#fff · border:1px solid #e9ebef · border-radius:16px · overflow:hidden`.

| Element | Spec | Binding |
|---|---|---|
| Header | `padding:18px 22px 14px · border-bottom:1px solid #f0f1f4`; title `15px/700`, subtitle `12.5px/500 · #7a828f · margin-top:3px` | `Commands` / `Activity by Claude Code command · {rangeLabel}` |
| Total strip | `padding:14px 22px 4px · display:flex · align-items:baseline · gap:8px`; figure `20px/800 · letter-spacing:-.4px`; caption `10.5px/600 · #a2abb8 · uppercase · letter-spacing:.5px` | `commands.total_runs` + literal `total runs` |
| Row | `padding:13px 0 · border-bottom:1px solid #f4f5f7 · display:flex · flex-direction:column · gap:8px`, inside `padding:4px 22px 16px` | `sc-for commands.items` |
| Command chip | `<code>` · `12.5px/600 · JetBrains Mono · color:#2a3441 · background:#f2f4f7 · padding:3px 8px · border-radius:6px`, nowrap + ellipsis | `items[i].command` — **verbatim, leading slash included**; the renderer never adds or strips one |
| Count | `13px/700 · flex:none`, with a trailing `10.5px/600 · #a2abb8 · margin-left:3px` `runs` | `items[i].count` |
| Bar track | `height:6px · border-radius:4px · background:#eef0f3 · overflow:hidden` | — |
| Bar fill | inline style bound directly | `items[i].barStyle` — pre-built CSS width from the API, max-of-range |

`#2a3441` is the command-chip ink; see § Token gaps.

**Empty list.** `items: []` with `total_runs: "0"` is a true empty state. Render the card with its
header and total strip, and in place of the rows a single centred line, `13px/500 · #7a828f`:
`No commands run in this period.` **[NEW]** — no mockup supplies empty-state copy for this list.
This is visually distinct from the Denied state (§ 2.5) because the card scaffolding, the cards row
above it, and the chart are all still present.

#### Formatting responsibility — what the renderer must and must not format

| Field | Arrives as | Renderer |
|---|---|---|
| `cards[].value` | pre-formatted string (`format_number()` / `format_duration()`) | render verbatim |
| `cards[].glyph`, `.label`, `.iconBg`, `.iconColor` | fixed server-owned constants | render verbatim |
| `daily_tokens.points[].value` | **pre-formatted string** | render verbatim in tooltips/labels; **must parse to a number for plotting** |
| `daily_tokens.period_total`, `.avg_per_day` | pre-formatted strings | render verbatim |
| `commands.total_runs` | pre-formatted string | render verbatim |
| `commands.items[].count` | **raw int** — the one documented exception (ADR-0009) | render as-is; do **not** apply K/M formatting, do not re-derive the bar from it |
| `commands.items[].barStyle` | pre-built CSS width string | bind directly |

> **Plotting note, carried forward from the contract, not invented here.** `DailyTokenSeries.points[].value`
> is a **pre-formatted string** (`"4.2M"`), unlike PGD-02's token-trend which returns raw ints and is
> what `DailyTokenTrendChart` was built against. A chart cannot plot `"4.2M"`. The renderer must
> either parse the magnitude suffix back to a number or the route must supply a raw series. **This is
> a contract question, not a design question** — flagged here because it blocks T-16, and recorded in
> § Open questions below rather than resolved by this file.

**Member identity in the header.** `avBg` and `initials` are derived client-side from `role` and
`member_name` exactly as Screen 1 § "Avatar colour and initials" specifies — same map, same
derivation, reused not re-decided. `PersonalUsageResponse` carries no identity fields at all, so the
header's name/role/avatar come from the **team row that was clicked**, not from the popup response.

---

### 2.4 Loading state — **[NEW]**

Opens **immediately** on row activation; the popup never waits on the fetch before appearing.

| Region | Loading treatment |
|---|---|
| Overlay + panel + header | Fully rendered. Name, role, avatar, and initials are already known from the clicked row — **no skeleton on the header**. |
| Range chips | Rendered, `disabled`, `cursor:not-allowed · opacity:.7` (the shipped `.toggleButton:disabled` rule) |
| Close button | Rendered and **enabled** — dismissal must never wait on a fetch |
| Cards row | 4 placeholder cards at the same geometry, text suppressed, `background:#f5f6f8` fills at the value/label positions — mirrors `ProgramSummaryCards`' `LOADING_PLACEHOLDER_COUNT` placeholder pattern |
| Chart | `.chartSkeleton` equivalent: `width:100% · height:180px · border-radius:10px · background:#f5f6f8`; stat block `.statSkeleton` (`88×20 · radius:6px · #f5f6f8`) |
| Commands | 6 placeholder rows (`hint-placeholder-count="6"` from the ARC mockup's own commands list) at row geometry: chip-shaped and bar-shaped `#f5f6f8` fills |

**Announcement.** The body region carries `aria-busy="true"` while loading, and a visually-hidden
`aria-live="polite"` region announces `Loading usage for {member_name}` on open and the populated
summary on arrival. Placeholder blocks are `aria-hidden`.

**Range switch.** A range change re-enters this state for the **chart and commands blocks only** —
the `cards` block is a to-date aggregate, unaffected by range (ADR-0009), so re-skeletoning it would
imply it changed. It stays populated across range switches.

---

### 2.5 Denied state (403) — **[NEW]**, the state this gate most exists for

**Contract.** `member_in_program_visibility` denies with a bare `HTTPException(403)` carrying **no
personal-usage fields** (AC-11/AC-12), logged `member_view_denied`. The renderer therefore has
nothing to render into cards, chart, or commands — and **must not render their scaffolding**.

**Hard rule: no scaffolding.** The denied body renders **no cards grid, no chart shell, no commands
card, and no placeholders of any kind.** An empty-but-present chart or a zeroed card row would assert
"this member's usage is zero", which is a different and false claim. This is the single most
important property of this state.

| Element | Spec |
|---|---|
| Panel | Same chrome, **`max-height` drops to content** — the panel shrinks to the message rather than holding a `760px` frame around one line |
| Header | Rendered unchanged (name, role, avatar are known from the clicked row and are not privileged data — the team table already displays them) |
| Range chips | **Not rendered.** There is no data for a range to scope; a live control over nothing is a false affordance |
| Body | `padding:32px 22px 34px`, centred column, `gap:10px` |
| Glyph | `44×44 · border-radius:11px · background:#f2f4f7 · color:#7a828f`, a lock glyph, `aria-hidden` |
| Headline | `14px/700 · color:#151a22` — `You don't have access to this member's usage` |
| Body copy | `12.5px/500 · color:#7a828f · max-width:42ch · text-align:center` — `Individual usage is visible to the member themselves and to CIO-level roles.` |
| Action | The close button in the header is the only action. **No retry button** — a retry implies the denial is transient; it is not |

**Distinguishability from empty data — required, and how it is achieved.** Three independent signals,
any one of which suffices:

1. **Structural** — the cards/chart/commands blocks are absent entirely; the empty-data case renders
   all three (populated cards, a flat-line chart, and the commands card with its "No commands run in
   this period." line).
2. **Chromatic/iconic** — a lock glyph on a neutral tile; no other state uses one.
3. **Copy** — the headline names *access*, never *data*. It must never read "No usage data" or
   "Nothing to show".

**Announcement.** The message container carries `role="status"`; focus stays on the close button
(the initial-focus target, unchanged by state) so a screen-reader user hears the denial without a
focus jump.

---

### 2.6 Error state — **[NEW]**

Any non-403 failure: network error, 5xx, `400 invalid_range`, or a malformed body.

| Element | Spec |
|---|---|
| Panel + header | Unchanged |
| Range chips | Rendered and **enabled** — changing range is itself a legitimate retry path |
| Body | `padding:32px 22px 34px`, centred column, `gap:10px`, matching the Denied body's geometry |
| Glyph | `44×44 · border-radius:11px · background:#f2f4f7 · color:#7a828f`, a warning glyph, `aria-hidden` — **a different glyph from Denied's lock**; the two states must not share one |
| Headline | `14px/700 · color:#151a22` — `Couldn't load this member's usage` |
| Body copy | `12.5px/500 · color:#7a828f` — `Something went wrong. Try again.` No status code, no server message surfaced to the user |
| Action | **Retry button**, reusing `DailyTokenTrendChart.module.css` `.retryButton` verbatim: `border:1px solid #e4e7ec · background:#fff · color:#151a22 · 12px/700 · padding:6px 14px · border-radius:8px · cursor:pointer`. Re-issues the same request at the current range |

The retry button is the **only** structural difference from the Denied body, and it is the
deliberate one: Error is transient and actionable, Denied is neither. `role="status"` on the
container; focus remains on the close button, **not** moved to Retry (an unrequested focus move on
error is hostile).

---

### 2.7 Responsive — desktop-only

Consistent with all six mockups (`docs/design/README.md` § Responsive, `tokens.md` § Responsive) and
with Screen 1's own position: **this popup is designed for desktop only.** No breakpoint is invented.

Narrow-width hostility, flagged rather than solved:

- The panel is `max-width:760px` inside a `24px`-padded overlay, so it degrades gracefully in *width*
  down to roughly 420px — the cards grid falls from 2×2 to 1×4 on its own via `auto-fit`.
- **The real hostility is vertical.** `max-height:min(78vh,760px)` on a short viewport (a landscape
  phone, ~380px tall) leaves ~200px of body region for three blocks. It scrolls, so nothing is
  unreachable, but the chart at `180px` tall nearly fills the entire scroll viewport on its own.
- The `180px` chart height and the `1000×240` viewBox are fixed; no narrow variant exists.

A mobile pass must decide whether this becomes a full-screen sheet rather than a centred panel. That
is undesigned and must be raised, not inferred.

---

### 2.8 Token gaps — values used here with no entry in `docs/design/tokens.md`

Flagged explicitly rather than silently adopted, following iteration 0's handling of
`QA Engineer → #d1495b` (since added to `tokens.md`):

| Value | Where | Status |
|---|---|---|
| `border-radius:18px` (panel) | EMD popup panel | **Not in `tokens.md` § Radius** (`16px` cards, `20px` pills, `11px`, `10px`, `9px`, `8px`, `6px`, `4px`, `2px`, `50%`). `18px` appears only on this modal panel. Kept as-is because it is real mockup markup and the modal is deliberately one step larger than a card; **should be added to § Radius as the modal-panel radius** rather than rounded to `16px`. |
| `box-shadow:0 24px 60px rgba(15,26,46,.28)` | EMD popup panel | **Not in `tokens.md` § Elevation**, which records exactly one shadow (`0 1px 2px rgba(15,26,46,.04)`) and states "the design is border-led, not shadow-led". A modal legitimately needs a lift token; this is the only one the system has. **Should be added to § Elevation as the modal/overlay shadow.** |
| `rgba(15,26,46,.42)` (overlay scrim) | EMD popup overlay | Derived from the Ink token `#0f1a2e` at 42% — no scrim token exists. **Should be added.** |
| `#f4f6f9` (close-button hover) | EMD popup close button | Not in the border/surface ramp (`#f2f4f7` and `#fafbfc` are the nearest). Kept verbatim from the mockup; **worth adding or reconciling to `#f2f4f7`** — that is a token decision, not one this file makes. |
| `#2a3441` (command-chip ink) | ARC + EMD commands list | Not in the text ramp (`#5b6472` · `#7a828f` · `#8a93a1` · `#9aa2ae` · `#a2abb8`) and darker than all of them. Already in use by the shipped commands panel, so this is pre-existing, not introduced here. **Should be added to § Color.** |
| `#151a22` (active chip ink, headline ink) | `segBtn()`, shipped `.toggleButtonActive` | Not in the text ramp; already shipped. Pre-existing. |
| `#f5f6f8` (skeleton fill) | Shipped `.chartSkeleton`/`.statSkeleton` | Not in the surface ramp; already shipped. Pre-existing. |
| `25px` vs `27px` KPI value | Cards | `25px` is the token; `27px` is the ARC mockup literal. **Resolved in favour of the token** (§ 2.3), matching the shipped component. |

No value above was invented for this design. Every one is either real mockup markup or already
shipped in `apps/web/src`; the gap is in `tokens.md`'s coverage, not in this spec's discipline.

### 2.9 Open questions — not design decisions, raised not resolved

1. **`daily_tokens.points[].value` is a pre-formatted string, not a number** (§ 2.3 Formatting).
   `DailyTokenTrendChart` plots raw ints (PGD-02). Either the renderer parses magnitude suffixes back
   to numbers — lossy and fragile — or the popup route supplies a raw series alongside. **A contract
   decision for planning, and the one item that could still block T-16's chart block.**
2. **Card grid arrangement at `760px`** lands 2×2 (§ 2.3). Accepted here; if a reviewer requires 1×4,
   the panel must widen to ≈940px and § 2.2's `max-width` changes with it.

## Not specified by the mockup

- ~~The entire member usage popup.~~ **Resolved** — see § "Screen 2: Member usage popup —
  ORIGINATED, NOT EXTRACTED". Still true that **no mockup backs it**: Screen 2 is originated design
  authored under `REQUIREMENTS.md` § Constraints' design gate, built from EMD's modal chrome +
  ARC's `MY USAGE` content language + `tokens.md`. A future canvas export supersedes it.
- ~~Row click, hover, focus, and selected states on the PGD team table.~~ **Resolved for the popup
  trigger** — see § 2.1, which specifies hover / focus-visible / pressed / open, the accessible
  name, and keyboard operability that T-16 must add. No *selection* state (a persistently selected
  row independent of the popup) is designed, because nothing in the story needs one.
- Empty, loading, and error states for the team panel.
- Row truncation, pagination, or "show more" — the panel renders every entry in `people` with no
  cap and no scroll container (unlike the EMD popup's `max-height:340px;overflow:auto`).
- An avatar colour for `QA Engineer` in `docs/design/tokens.md` (the mockup's `#d1495b` is
  untokenised).
- Any sort control — ordering is fixed, not user-selectable.
- A **mobile/narrow variant of the popup** — desktop-only, same as every other surface here (§ 2.7).
  Whether it becomes a full-screen sheet is undesigned.
- **Modal-panel radius (`18px`), modal shadow, and the overlay scrim colour** as `tokens.md`
  entries — used by § 2.2 from real EMD markup, but absent from `tokens.md` § Radius / § Elevation /
  § Color. Full list in § 2.8.

## Responsive

Desktop-only, consistent with all six mockups (`docs/design/README.md` § Responsive), and a real
gap against the project's stated responsive web target. The enclosing section's
`minmax(min(100%,360px),1fr)` collapses the two-up to one column under ~736px, but this panel's
own internals have no narrow-width variant — and the fixed `1.8fr 1fr 1fr 1fr 1fr` five-column
grid is the most narrow-hostile layout on the page: at 360px each numeric column is ~52px while
`Avg / session` alone needs ~90px for its header. Mobile column collapse, horizontal scroll, or a
card layout is undesigned and must be raised before a mobile breakpoint ships.

**Screen 2 (popup)** is likewise desktop-only — see § 2.7 for its own narrow-width analysis. It adds
one distinct hostility the team panel does not have: the constraint is **vertical**, not horizontal.
`max-height:min(78vh,760px)` on a short viewport leaves too little room for the popup's three
stacked blocks, and the `180px` chart nearly fills the scroll viewport on its own. The panel's width
degrades gracefully (the cards grid re-flows via `auto-fit`); its height does not. A full-screen
sheet is the likely mobile answer and is undesigned.
