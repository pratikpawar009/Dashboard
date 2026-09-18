# DESIGN: OVW-04 — Program board

**Provenance**: hand-authored 2026-09-18 during `/arh-plan-requirements` Phase 2. `ux-agent` is not
installed in this repo — `.claude/agents/` has no `ux-agent.md` — the same gap SHP-01, PGD-01,
OVW-01 and OVW-05 each hit and recorded in their own `DESIGN.md` files. This is the **fifth**
occurrence; OVW-01 reclassified it from surprise to standing condition and carried it forward for a
decision on whether to install the agent. Nothing new to add — this file was likewise written
directly from the design source instead of generated. It is a **pre-implementation spec**: neither
the route nor any component below exists. **The mockup, not this file, is the source of truth on any
disagreement.**

**Design source**: `docs/design/mockups/CIO Portfolio Dashboard.html` (`docs/design/schema.json` →
`designSystem.pages.features.OVW`). A Claude Design canvas export — it must be decoded before the
markup is readable; `docs/design/README.md` § "These are bundler outputs" carries the procedure.
Decoded document: 39,478 characters / 774 lines — identical decode to OVW-01's and OVW-05's. Line
references below are into that decode.

## Scope

One region, two screens per `REQUIREMENTS.md` § Screen inventory. The decoded document's section
comments are `BRAND BAR`, `HEADER`, `CONTENT`, `ORG SUMMARY`, `ORG MONTHLY TOKEN COST BAR CHART`,
`MONTHLY ACTIVE USERS BY ROLE`, `PROGRAM ADOPTION HEALTH`, `PROGRAM LEADERBOARD`. **This story owns
`PROGRAM LEADERBOARD` only** (L495–559).

| Screen | Region | Component | Mockup anchor |
|---|---|---|---|
| Program leaderboard | `/overview`, new section below the adoption indicator | `ProgramLeaderboard` + `ProgramCard` (new) | `<!-- PROGRAM LEADERBOARD -->` L495–559 |
| Program card navigation | same card — the whole card *is* the affordance | `ProgramCard`'s root `<a>` | L508, L530 |

Explicitly **not** in scope though the same mockup renders them: `ORG SUMMARY` and
`PROGRAM ADOPTION HEALTH` (OVW-01, shipped), the token-cost bar chart and MAU-by-role (OVW-02/03),
the brand bar and header (SHP-01/OVW-05, shipped).

---

## Region — `PROGRAM LEADERBOARD`

### Section header (L497–503) — literal copy, static, never bound

| Element | Exact text / form |
|---|---|
| Heading dot | `<span style="width:8px;height:8px;border-radius:2px;background:#c08a1e">` — small square dot preceding the heading |
| Section heading | `Program board` — `font-size:14px; font-weight:700; letter-spacing:-.2px` |
| Heading suffix | `— all programs using Harness` — `font-size:12px; color:#9aa2ae; font-weight:500` |
| Right slot (L502) | **empty `<div>`**, styled but with no content and no binding |

Three notes an implementer needs:

1. **The rendered heading is `Program board`, not "Program leaderboard".** The section *comment* is
   `PROGRAM LEADERBOARD` and the PRD/story use "leaderboard" throughout. Render the mockup's text.
   OVW-01 hit the identical comment-vs-rendered-text split (`PROGRAM ADOPTION HEALTH` →
   `Adoption Level`) and resolved it the same way.
2. **The heading dot is `#c08a1e`**, not the `#2a6fdb` OVW-01's `ORG SUMMARY` dot uses. Each
   section carries its own dot colour. `#c08a1e` is already in `tokens.md` as the `Maintenance`
   program-type colour; it has no *section-dot* entry. See § Token gaps.
3. **The empty right slot is not a placeholder for something this story should fill.** It carries a
   style and no binding. Ship the container or omit it, but do not invent a control (count, filter,
   sort) for it — `CLAUDE.md` § Design system forbids exactly that. § PRD-vs-mockup gaps records
   why this matters for pagination.

### List construct (L506–507)

```html
<div style="display:flex;flex-direction:column;gap:14px">
  <sc-for list="{{ programs }}" as="p" hint-placeholder-count="6">
```

A vertical stack with a `14px` gap — **not** a grid. `hint-placeholder-count="6"` is a **contract,
not a sample size**, per the reading PGD-01 established and OVW-01 reaffirmed: the loading state
renders exactly **6** placeholder cards at populated-card geometry with text suppressed. Note that
`6` also happens to be the mockup's sample program count; the attribute is still the contract, and
6 is independent of the PRD's `page_size=20` default. See § PRD-vs-mockup gaps.

### Card root (L508) — the navigation affordance

```html
<a href="{{ p.href }}" target="_top" style="{{ p.cardStyle }}" style-hover="{{ p.cardHover }}">
```

**The entire card is a single `<a>`.** There is no separate button, no click handler, no nested
interactive element. The `→` glyph at L530 is decorative chrome *inside* that anchor, not a second
affordance. `REQUIREMENTS.md` § Screen inventory's second row ("Selecting a card **or its arrow**")
describes one link, not two targets.

`p.cardStyle` and `p.cardHover` are derived client-side per the PRD's presentation-vs-data
constraint (`docs/design/README.md` § "templates also bind presentation", OVW-01-FR-2 precedent) —
never shipped as CSS strings. Their mockup values (`renderVals()`, L698–699):

| Property | Value |
|---|---|
| Rest | `display:block; text-decoration:none; color:inherit; cursor:pointer; background:#fff; border:1px solid #e9ebef; border-left:4px solid <typeColor>; border-radius:16px; padding:20px 22px 18px; transition:border-color .15s, box-shadow .15s, transform .15s` |
| Hover | `border-color:#d4dae4; box-shadow:0 10px 26px rgba(15,26,46,.10); transform:translateY(-2px)` |

The **`4px` left border is the program-type colour** — the card's only type-coded chrome besides the
avatar and chip. `p.href` is `"/programs/{program_id}"` per AUTH-04's route convention; the mockup's
own `'Program Detail.html?p=' + p.slug` is a canvas-local file link with no bearing on the app.

`box-shadow:0 10px 26px rgba(15,26,46,.10)` and `border-color:#d4dae4` are both absent from
`tokens.md`. See § Token gaps.

### Top row (L510–531) — identity

| Element | Line | Binding | Style |
|---|---|---|---|
| Row | L510 | — | `display:flex; align-items:center; gap:14px` |
| Avatar tile | L511 | `p.avatar` (abbreviation), `p.avatarStyle` | `46×46` · `border-radius:13px` · `background:<typeBg>` · `color:<typeColor>` · centred flex · `17px` / `800` · `letter-spacing:-.5px` · `flex:none` |
| Identity column | L512 | — | `flex:1; min-width:180px` |
| Title row | L513 | — | `display:flex; align-items:center; gap:10px; flex-wrap:wrap` |
| Program name | L514 | `p.name` | `16px` / `800` / `letter-spacing:-.3px`, inherits body ink `#151a22` |
| Type chip | L515 | `p.ptype`, `p.typeChip` | `display:inline-flex; align-items:center; gap:6px` · `11px` / `700` · `color:<typeColor>` · `background:<typeBg>` · `padding:3px 10px` · `border-radius:20px` · `letter-spacing:.1px` |
| Description | L517 | `p.scope` | `12.5px` / `500` / `#5b6472` · `margin-top:5px` · `line-height:1.45` · **`max-width:600px`** |
| Navigation glyph | L530 | literal `→` | `34×34` · `border-radius:10px` · `background:#f2f4f7` · `color:#5b6472` · centred flex · `16px` / `700` · `flex:none`; hover `background:#e9edf3` |

**Two field-name notes.** The mockup binds `p.scope` for what the PRD calls `description`, and
`p.ptype` for `type`. The PRD's wire names win — this is a rename, not a contract mismatch. And the
avatar's `p.avatar` is a **derived abbreviation** (`M`/`G`/`B`/`MT`), not a stored value: the PRD's
`icon: str` field is redundant with `type`, which the existing
`apps/web/src/lib/programStyle.ts` already maps. See § PRD-vs-mockup gaps.

**Type colour source.** `tMap` (decode L682–687) is byte-identical to `docs/design/tokens.md`
§ Program type colours, already implemented in `programStyle.ts` with its documented
`?? PROGRAM_TYPE_COLORS["Migration"]` fallback for `Upgradation`. **Reuse it. Do not re-derive.**

| Program type | Colour | Background | Avatar abbr. |
|---|---|---|---|
| Migration | `#2a6fdb` | `#eaf1fc` | `M` |
| Greenfield feature development | `#1f8a5b` | `#e8f5ee` | `G` |
| Brownfield feature development | `#7c5cff` | `#efebff` | `B` |
| Maintenance | `#c08a1e` | `#fdf3e0` | `MT` |

`#e9edf3` (the `→` hover) is not in `tokens.md`. See § Token gaps.

### Body grid (L533)

```
display:grid; grid-template-columns:1.5fr 2.2fr; gap:24px;
margin-top:16px; padding-top:16px; border-top:1px solid #f0f1f4; align-items:stretch
```

Two columns — sparkline panel left (`1.5fr`), metrics right (`2.2fr`) — separated from the top row
by a `1px solid #f0f1f4` rule.

### Body left — monthly token consumption panel (L535–544)

| Element | Line | Binding | Style |
|---|---|---|---|
| Panel | L535 | — | `background:#fafbfc` · `border:1px solid #eef0f3` · `border-radius:12px` · `padding:12px 14px 8px` |
| Panel header row | L536 | — | `display:flex; align-items:center; justify-content:space-between; margin-bottom:6px` |
| Panel label | L537 | literal `Monthly token consumption` | `10.5px` / `700` / `#9aa2ae` · `text-transform:uppercase` · `letter-spacing:.3px` |
| MoM chip | L538 | `p.momLabel`, `p.momColor`, `p.momBg` | `11px` / `700` · `padding:2px 8px` · `border-radius:20px` |
| Chart slot | L541 | `p.miniChart` | fixed `height:56px` |

#### MoM change indicator

Computed in `renderVals()` (L689–691, L703–705):

```js
mom = Math.round(((mo.at(-1) - mo.at(-2)) / mo.at(-2)) * 100);
up  = mom >= 0;
momLabel = (up ? '▲ ' : '▼ ') + Math.abs(mom) + '%';
momColor = up ? '#1f8a5b' : '#d1495b';
momBg    = up ? '#e8f5ee' : '#fdeaec';
```

| Direction | Glyph | Colour | Background |
|---|---|---|---|
| `up` | `▲` | `#1f8a5b` (Success) | `#e8f5ee` |
| `down` | `▼` | `#d1495b` | `#fdeaec` |
| `flat` / neutral | **no mockup value — see below** | | |

**The glyph carries the direction, not colour alone** — which is exactly the non-colour-reliant
encoding `REQUIREMENTS.md` § NFR Accessibility requires, satisfied by the mockup as drawn. No extra
affordance needed. `#d1495b`/`#fdeaec` are the QA-persona red and the EMD/PGD negative-delta pair;
`#fdeaec` is absent from `tokens.md`. See § Token gaps.

**The mockup has no `flat` and no neutral branch.** Its `up = mom >= 0` is binary — a `0%` change
renders `▲ 0%` in green. `REQUIREMENTS.md` **OVW-04-FR-3** defines a third `"flat"` direction plus a
`null`/`null` neutral state for <2 sparkline points. Neither exists in the design source. Per
`docs/design/README.md` § Recorded divergences' generalisation ("render the weaker true string
rather than the stronger unverifiable one"), the rendering for these two cases:

| `mom_direction` | Chip |
|---|---|
| `"up"` | `▲ {pct}%` on `#1f8a5b` / `#e8f5ee` |
| `"down"` | `▼ {pct}%` on `#d1495b` / `#fdeaec` |
| `"flat"` | `— 0%`, text `#5b6472` (`text-700`, 5.98:1 on the `#fafbfc` panel), background `#f0f1f4`. Same chip geometry |
| `null` (<2 points) | **chip omitted entirely** — the panel header renders the label alone. No glyph, no colour, no "n/a" copy |

The `flat` pair is the one value in this file the design source does not settle. Flagged in § Open
design items rather than presented as sourced.

#### Chart — `spark()` (decode L625–646)

`p.miniChart` binds a **pre-rendered React SVG**, not data. The frontend owns the chart entirely;
the wire carries `sparkline.points[]` raw ints (OVW-04-FR-1). Port the geometry verbatim, the way
`DailyTokenTrendChart.tsx` ports the mockup's `areaChart()`:

| Constant | Value |
|---|---|
| viewBox | `0 0 240 56`, `preserveAspectRatio:"none"`, `width:100%`, `height:56px`, `display:block` |
| `pad` | `4` |
| x | `pad + (i / (n - 1)) * (W - pad*2)` |
| y | `pad + (1 - (v - min) / rng) * (H - pad*2 - 6)`, `rng = (max - min) \|\| 1` |
| Line | `stroke:<typeColor>` · `stroke-width:2.4` · `fill:none` · round cap + join |
| Area fill | `linearGradient` top→bottom, `<typeColor>` at `0.22` → `0` opacity; path closes to `y = H - pad` |
| End dot | `r:4`, `fill:#fff`, `stroke:<typeColor>`, `stroke-width:2.4` at the last point |

The stroke/fill/dot colour is **the program-type colour**, not a fixed chart blue — each card's
sparkline is tinted like its own left border, avatar and chip.

**Two divide-by-zero guards the mockup's demo data never reaches** (its `monthly` arrays are all
12-point, all non-zero) but real data does — same class of guard `DailyTokenTrendChart.tsx`'s
`MIN_AXIS_MAX` already documents:

- `n === 1` → `(i / (n - 1))` is `0/0`. One point renders as a single dot; centre it or clamp `xs`
  to `pad`. Do not render a line.
- `n === 0` → empty panel body at the fixed `56px` height. No axes, no "no data" copy; the MoM chip
  is already omitted by the `null` rule above.

`rng = (max - min) || 1` already guards the all-equal case, including an all-zero series.

### Body right — metrics + repos progress (L545–557)

Column: `display:flex; flex-direction:column; gap:12px; justify-content:center`.

#### Metric grid (L546, L534)

```html
<div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(90px,1fr));gap:12px">
  <sc-for list="{{ p.metrics }}" as="m" hint-placeholder-count="4">
```

`hint-placeholder-count="4"` — exactly four boxes, always. Per entry (L536–541 of the card body):

| Element | Binding | Style |
|---|---|---|
| Icon | `m.icon` | `12px` · `font-family:'JetBrains Mono', monospace` |
| Label | `m.label` | `10px` / `700` · `text-transform:uppercase` · `letter-spacing:.3px` |
| Icon+label row | — | `display:flex; align-items:center; gap:6px; color:#9aa2ae` |
| Value | `m.value` | `19px` / `800` · `letter-spacing:-.5px` · `color:#151a22` · `margin-top:5px` |

The four entries are **server-owned presentation constants in fixed order** (decode L707–712),
the same `{glyph, label, value}` pattern ADR-0007 establishes for `program-detail-api`'s summary
cards — only `value` varies per program:

| # | Icon | Label | PRD wire field |
|---|---|---|---|
| 1 | `⬡` | `Total tokens` | `metrics.tokens` |
| 2 | `⤴` | `Releases via Harness` | `metrics.releases` |
| 3 | `✦` | `Features via Harness` | `metrics.features` |
| 4 | `⚇` | `Active contributors` | `metrics.active_contributors` |

**`REQUIREMENTS.md` OVW-04-FR-1 omits the icon and the label.** Its `metrics` object carries four
pre-formatted value strings only. See § PRD-vs-mockup gaps — the labels above are the contract
either way, whether they cross the wire or are frontend constants.

**Value formatting.** The mockup's `fmtM` (`n >= 1000 ? (n/1000).toFixed(2)+'B' : n.toFixed(1)+'M'`)
applies to `Total tokens` only; the other three are `String(n)` plain counts. FR-1 routes all four
through `format_number()` server-side, consistent with `docs/design/README.md` § "Values arrive
pre-formatted". `21`/`34`/`61` render identically either way; only `Total tokens` differs in
magnitude suffix, and `format_number()` is the established precedent.

#### Repos-with-Harness progress (L548–556)

| Element | Line | Binding | Style |
|---|---|---|---|
| Header row | L549 | — | `display:flex; align-items:center; justify-content:space-between; margin-bottom:6px` |
| Label | L550 | literal `Repos with Harness installed` | `10px` / `700` · `text-transform:uppercase` · `letter-spacing:.3px` · `#9aa2ae` |
| Ratio | L551 | `p.repoLabel` | `12px` / `800` · `#151a22` · `font-family:'JetBrains Mono', monospace` |
| Track | L553 | — | `height:7px` · `background:#eef0f3` · `border-radius:20px` · `overflow:hidden` |
| Fill | L554 | `p.repoBarStyle` | `height:100%` · `width:<pct>%` · `background:<typeColor>` · `border-radius:20px` |

Derived client-side from the two raw ints per FR-1:

- `repoLabel` = `` `${installed} / ${total}` `` — **spaces around the slash** (`5 / 6`), matching
  `p.repos + ' / ' + p.reposTotal` (L706). The PRD's prose says `"5/6"`; the mockup spaces it.
- `repoPct` = `Math.round((installed / total) * 100)` (L700).

**`total === 0` guard.** `renderVals()` divides unguarded; its demo data never has a zero total. A
program with no repos yields `NaN%`. Render `0 / 0` with a `0%`-width fill on the `#eef0f3` track —
no error, no omission, mirroring OVW-01's `adoption_percent: null` → flat-bar precedent.

The fill is again **the program-type colour** — fourth type-coded element on the card.

---

## States

| State | Rendering |
|---|---|
| Populated | N cards in the backend's `tokens DESC` array order — **order is the contract**, never re-sorted client-side (ADR-0007's ordering discipline, FR-2) |
| Loading | exactly **6** placeholder cards (`hint-placeholder-count="6"`, L507) at populated geometry, text suppressed. The PRD renders this page server-side with no client refetch, so this state is reachable only via Suspense/streaming; spec'd because the mockup contracts it |
| Empty (no programs, AC-5 / FR-4) | section header renders, card stack is empty. **The mockup has no empty variant and no empty-state copy — do not invent one.** Same position OVW-01 took for its all-zero cards |
| Error (403 non-CIO, AC-2 / FR-4) | the existing shipped `OverviewErrorPanel` (`apps/web/src/components/OverviewErrorPanel.tsx`, OVW-01). The mockup shows no error region; reuse, do not design |
| Per-card partial data | a card never fails as a unit. `sparkline.points: []` → empty chart panel + omitted MoM chip (above); `repos_total: 0` → `0 / 0` flat bar. Every other field still renders. FR-3's "never blocks the rest of the card" |

---

## PRD-vs-mockup gaps

Raised, not designed around, per `CLAUDE.md` § Design system. None blocks the PRD; all five want a
decision before implementation.

1. **Pagination has no UI.** `REQUIREMENTS.md` OVW-04-FR-1/FR-2 specify `page` / `page_size` /
   `total` with a `page_size=20` default and a `100` clamp. **The mockup contains no pager, no
   "showing N of M", no infinite-scroll sentinel, and no count** — its one candidate slot, the
   section header's right-hand `<div>` (L502), is styled but empty and unbound. The mockup's six
   sample programs all render in one stack. So the wire is paginated and the UI is not. Three
   options, none inventable here: (a) fetch page 1 only and render what arrives, leaving `total` an
   API-level affordance (smallest, matches the mockup exactly); (b) raise `page_size` to cover a
   realistic org and defer paging to a later story; (c) design a pager, which requires a design
   decision the source does not supply. **Recommend (a)** and record it — it is the only option
   that ships what the mockup shows.

2. **`hint-placeholder-count="6"` vs `page_size=20`.** The loading contract is 6 cards; the default
   page is 20. Not a conflict — one is a skeleton count, the other a data page — but an implementer
   will reasonably ask. Render 6 placeholders regardless of `page_size`, per the attribute.

3. **`icon` is redundant on the wire.** FR-1 ships `icon: str` ("avatar abbreviation source (e.g.
   `G`)"). The mockup derives the abbreviation from `ptype` via `tMap` (L682–687), and
   `apps/web/src/lib/programStyle.ts` already implements exactly that map with its documented
   `Upgradation → Migration` fallback. Shipping `icon` creates a second source of truth for a value
   already derivable from `type`, and can disagree with the colour pair derived alongside it.
   **Recommend dropping `icon` from the response** and deriving it with `programStyle.ts` — which
   is also what the PRD's own presentation-vs-data constraint implies, since the abbreviation
   travels with the colours it is keyed by.

4. **`metrics` loses the icon and the label.** FR-1's `metrics` is four pre-formatted value strings.
   The mockup binds `{icon, label, value}` per entry (L707–712) and OVW-01's own `orgKpis` /
   PGD-01's `summary` both ship `{glyph, label, value}` as server-owned constants (ADR-0007). This
   story's shape is the outlier. Either is renderable — the labels are fixed constants either way —
   but the divergence from two sibling precedents on the same page should be deliberate. Flagged,
   not decided.

5. **`flat` has no design.** FR-3 defines a third `mom_direction` the mockup's binary `mom >= 0`
   never produces, and a `null` neutral state for <2 points. § MoM change indicator spec'd both
   from `tokens.md` values; the `flat` chip pair (`#5b6472` on `#f0f1f4`) is the only value in this
   file not taken from the design source.

Also noted, not a gap: the rendered heading is `Program board`, while the PRD, story and section
comment all say "leaderboard". The mockup's text ships.

---

## Design QA — contrast audit

New and newly-reachable pairs only. WCAG 2.2 relative-luminance formula; 4.5:1 normal text, 3:1
large text (≥18.66px bold) and non-text.

| Element | fg | bg | Ratio | Bar | |
|---|---|---|---|---|---|
| Program name (16px/800) | `#151a22` | `#ffffff` | 17.46 | 4.5 | PASS |
| Metric value (19px/800) | `#151a22` | `#ffffff` | 17.46 | 3.0 | PASS |
| Repos ratio (12px/800) | `#151a22` | `#ffffff` | 17.46 | 4.5 | PASS |
| Description | `#5b6472` | `#ffffff` | 5.98 | 4.5 | PASS |
| Nav glyph `→` | `#5b6472` | `#f2f4f7` | 5.57 | 4.5 | PASS |
| Nav glyph `→`, hover | `#5b6472` | `#e9edf3` | 5.29 | 4.5 | PASS |
| MoM chip, up | `#1f8a5b` | `#e8f5ee` | 3.90 | 4.5 | **FAIL** |
| MoM chip, down | `#d1495b` | `#fdeaec` | 3.94 | 4.5 | **FAIL** |
| MoM chip, flat (spec'd) | `#5b6472` | `#f0f1f4` | 5.55 | 4.5 | PASS |
| Type chip, Migration | `#2a6fdb` | `#eaf1fc` | 4.35 | 4.5 | **FAIL** |
| Type chip, Greenfield | `#1f8a5b` | `#e8f5ee` | 3.90 | 4.5 | **FAIL** |
| Type chip, Brownfield | `#7c5cff` | `#efebff` | 3.96 | 4.5 | **FAIL** |
| Type chip, Maintenance | `#c08a1e` | `#fdf3e0` | 3.02 | 4.5 | **FAIL** |
| Avatar abbr. (17px/800), Maintenance | `#c08a1e` | `#fdf3e0` | 3.02 | 3.0 | PASS (large) |
| Section heading suffix | `#9aa2ae` | `#ffffff` | 2.60 | 4.5 | **FAIL — inherited** |
| Panel label / metric label | `#9aa2ae` | `#fafbfc` / `#ffffff` | 2.55 / 2.60 | 4.5 | **FAIL — inherited** |
| Sparkline stroke (non-text), Maintenance | `#c08a1e` | `#fafbfc` | 2.98 | 3.0 | **FAIL (marginal)** |
| Repos bar fill (non-text), Greenfield | `#1f8a5b` | `#eef0f3` | 3.72 | 3.0 | PASS |
| Card left border (non-text), Maintenance | `#c08a1e` | `#ffffff` | 3.02 | 3.0 | PASS |

**Every failure is the mockup's own value, reproduced byte-exactly** rather than diverged from
unilaterally — the same position SHP-01 and OVW-05 took. Two observations for the carry-forward:

- The **type chips and the MoM chip fail at every one of their colour pairs**, all in the 3.0–4.4
  range. This is a systemic property of the design's tint-on-tint chip recipe, not an OVW-04 defect;
  the same pairs already ship in `ProgramContext.tsx` (PGD-01) and `ReleasesList.tsx` (PGD-03). Any
  fix is a token-level decision with blast radius across all six dashboards.
- `#9aa2ae` at 2.55–2.60:1 is the darkest failure on the card and is *already* the codebase's most
  widely shipped label grey. Same standing carry-forward `tokens.md` records.

Nothing here is fixed in this story. Darkening a global ramp value is a design decision, not an
implement-phase edit.

## Keyboard and assistive tech

- The card is a real `<a href>` — native tab order, native Enter activation, native focus. **No
  `tabindex`, no `role`, no key handler.** Exactly one tab stop per card, and the `→` glyph must not
  become a second focusable element.
- **Accessible name.** The anchor wraps the whole card, so its computed name is the concatenation of
  every text node inside — name, type, description, chip, four metrics, ratio. Give the anchor an
  explicit `aria-label` (e.g. `` `${name} — open program detail` ``) so the name is short and the
  destination is stated. The `→` glyph is decorative: `aria-hidden="true"`.
- **Focus ring.** The repo has no `:focus`/`:focus-visible` rule anywhere in `apps/web/src` and the
  mockups specify no interactive states at all — no hover on anything but this card, no focus, no
  disabled. Use `outline:2px solid #2a6fdb; outline-offset:2px`, the value OVW-05 established as the
  codebase's first focus rule; it clears WCAG 1.4.11's 3:1 bar on `#ffffff` (4.78:1). Stated as the
  WCAG/browser-default fallback per `.claude/rules/project-standards.md`, not this team's convention.
  `transform:translateY(-2px)` on hover must not be the only focus feedback.
- **The MoM chip's direction is glyph-encoded** (`▲`/`▼`/`—`), satisfying the non-colour-reliant NFR
  without additional markup. Those glyphs need an accessible equivalent — `aria-label="up 12 percent"`
  or a visually-hidden word — since `▲` has no reliable screen-reader pronunciation.
- **The sparkline is decorative.** `role="img"` with an `aria-label` summarising the trend, or
  `aria-hidden="true"` with the MoM chip carrying the meaning. The chip already states the trend
  numerically, so `aria-hidden` on the SVG is sufficient and simpler.
- `prefers-reduced-motion`: the card's `transition:… transform .15s` and the `-2px` lift should be
  suppressed. Not specified by the mockup; standard practice, stated as such.

## Form factors

**Desktop-only.** `docs/design/README.md` and `docs/design/tokens.md` § Responsive both record all
six mockups as a fixed `1360px` column with no breakpoints, against `CLAUDE.md`'s "Web (desktop +
mobile responsive)" target. `REQUIREMENTS.md` § Scope already lists mobile/responsive as out.

Two card constructs are hard-coded to desktop width and will need a real breakpoint decision when
the responsive pass happens — recorded so the pass has a starting list, not designed here:

- the body grid's `1.5fr 2.2fr` two-column split (L533), which has no stacking rule;
- the description's `max-width:600px` (L517), a desktop measure with no fluid equivalent.

The metric grid's `repeat(auto-fit, minmax(90px, 1fr))` (L546) is already intrinsically fluid and
reflows without a breakpoint.

## Tokens

`docs/design/tokens.md` holds the extracted palette, type scale and radii. Literal values above are
byte-exact from the decoded inline styles; the mockups carry **inline styles only**, no custom
properties and no utility classes, so there is no token *reference* in the markup to map back.
Prefer the named token where one matches, fall back to the literal where it does not.

Matched: `primary` `#2a6fdb` · `success` `#1f8a5b` · `text-700` `#5b6472` · `text-400` `#9aa2ae` ·
`border-100` `#e9ebef` · `surface-300` `#eef0f3` · `surface-200` `#f0f1f4` · `surface-150` `#f2f4f7`
· `surface-50` `#fafbfc` · `card` radius `16px` · `pill` radius `20px` · `size-body-sm` `12.5px` ·
`size-caption` `11px` · `size-caption-sm` `10.5px` · the full § Program type colours table.

### Token gaps

Present in this region, absent from `tokens.md`. Added here for the record; adding them to
`tokens.md` is a T-task for implementation, not a decision this file makes.

| Value | Role |
|---|---|
| `#c08a1e` | **section heading dot** for `PROGRAM LEADERBOARD`. Already in `tokens.md` as the `Maintenance` type colour — same hex, different role; no new colour, but no section-dot token exists either |
| `#d4dae4` | card hover border |
| `#e9edf3` | nav-glyph hover background |
| `#fdeaec` | MoM-down chip background (the `#d1495b` QA red's tint; the red is tokenised, the tint is not) |
| `#151a22` | body ink — used by three values here. `tokens.md` records `ink` as `#0f1a2e`; `#151a22` is the mockups' `body{color}` and is a *different* value. Already noted by OVW-05 § Tokens |
| `0 10px 26px rgba(15,26,46,.10)` | card hover elevation. `tokens.md` § Elevation records two shadows (card `…,.04`, modal `…,.28`); this is a third |
| `12px` radius | sparkline panel. Between the `16px` card and `11px` icon-tile steps; `tokens.md` § Radius lists neither `12px` nor `13px` (the avatar tile) |
| `46×46` / `13px` radius | program avatar tile. Larger than the `34×34`/`50%` identity avatar and the `34×34`/`10px` nav glyph |
| `10px` / `700` uppercase | metric + repos label style. `tokens.md` § Typography's scale bottoms out at `10.5px`; `10px` is a new step |
| `19px` / `800` | metric value. `tokens.md` records `19px` as the *page title* size; this is a second role at a different weight |

## Open design items for the gate

1. **Pagination UI** — § PRD-vs-mockup gaps item 1. Recommend option (a): render page 1, no pager,
   matching the mockup exactly. Needs a decision, not an invention.
2. **`flat` MoM chip pair** — the one value here no source settles. Spec'd `#5b6472` on `#f0f1f4`
   from `tokens.md`; flagged rather than presented as sourced.
3. **`icon` on the wire** — § gap 3. Recommend dropping it and deriving from `type` via the shipped
   `programStyle.ts`. A structural call (`.claude/rules/reusability-baseline.md`), not a visual one.
4. **`metrics` entry shape** — § gap 4. Four value strings (FR-1) vs the `{glyph, label, value}`
   both sibling endpoints on this page already ship. Either renders; pick deliberately.
5. **Chip contrast is systemically below AA** — every type-chip and MoM-chip pair lands 3.0–4.4:1.
   Already shipped elsewhere; a token-level fix with six-dashboard blast radius. Standing
   carry-forward, not this story's.

None blocks the PRD. Items 1–4 need a decision before the components are built; item 5 is a
standing carry-forward.
