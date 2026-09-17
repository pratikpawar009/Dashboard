# DESIGN — PGD-05 Project team table + per-member usage popup

**Provider**: `html-mockup` · **Source**: `docs/design/mockups/Program Detail.html` (PGD epic, per `docs/design/schema.json`), `<!-- TEAM -->` section
**Iteration**: 0 · **Status**: extracted from the authored mockup — no new design work

The mockup is authored, not generated here. It is a bundler output — see `docs/design/README.md`
for the decode snippet before diffing or grepping.

PGD-05 ships **both** halves (PRD § Scope): the endpoint *and* the team-table UI plus popup
wiring. Screen 1 below is fully specified by the PGD mockup. **Screen 2 is not in the PGD
mockup at all** — see § "The popup is not in this mockup" before building it.

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

## Screen 2: Member usage popup

### The popup is not in this mockup

**`docs/design/mockups/Program Detail.html` contains no popup, modal, overlay, or dialog.**
Verified against the decoded markup: the file's only section comments are `BRAND BAR`, `HEADER`,
`CONTENT`, `PROJECT SUMMARY`, `DAILY TOKEN CONSUMPTION`, `RELEASES VIA HARNESS`,
`COMMANDS + TEAM`, `COMMANDS`, `TEAM` — the document ends at `</section>` after the team card.
Its team rows carry **no `sc-camel-on-click` and no `cursor:pointer`**; the only interactive
elements on the whole page are the range chips and the program switcher.

Per `CLAUDE.md` § Design system — "If a story seems to need something the mockups do not show,
stop and raise it. Do not design it." — **this file designs no popup.** What follows is the
evidence a planner needs to resolve it, not a spec to build from.

### What exists instead, and why it is not a substitute

`docs/design/mockups/Engineering Manager Dashboard.html` — a **different** mockup, for the EMD
epic, which `docs/design/README.md` § Screen inventory describes as "As Program Detail, plus
member-command popup" — carries a `<!-- MEMBER COMMAND POPUP -->` section and clickable team
rows (`sc-camel-on-click="{{ p.onClick }}"` + `cursor:pointer` + `style-hover:#f7f9fb`, the one
markup delta from the PGD team row, which is otherwise byte-identical).

That popup is **not the popup PGD-05 specifies**, on two counts:

1. **Wrong epic.** It belongs to EMD in `docs/design/schema.json`, not PGD. Lifting it into a PGD
   story is exactly the "invent a screen" the design rule forbids.
2. **Wrong content.** It renders a *command list* — avatar, name, `{{ popup.role }} · commands
   executed`, a `total runs` figure, its own 7D/30D/90D chips, and an `sc-for` of
   command/count/bar rows (the same shape as PGD-04's panel). PGD-05 AC-9/AC-10 require a popup
   rendering **`personal-usage-api`'s response verbatim** — `{cards, daily_tokens, commands}`
   (ADR-0009): a 4-card row, a daily-tokens chart, and a commands list. The EMD popup has **one**
   of those three, and its `total runs` header has no counterpart in the SHP-02 shape. It cannot
   render `personal-usage-api` without being redesigned.

### Consequence for PGD-05

The PRD's own Scope names "the popup wiring that opens **SHP-02's existing personal-usage popup
component**" — i.e. the intended design source is SHP-02's shipped component, not a PGD mockup.
That is coherent, and it is the route to take. Two things must still be settled before a renderer
ships, and neither is a UX decision this file can make from the PGD mockup:

- **The trigger.** The PGD team row is not clickable in the mockup. Making it clickable is a real
  addition — it also carries the NFR-008 obligation (accessible name, keyboard-operable) the PRD
  states. The EMD row supplies the visual treatment a planner would most likely mirror
  (`cursor:pointer`, `style-hover:background:#f7f9fb`) — cited as precedent, **not** adopted here.
- **The modal chrome.** Overlay, panel width, close affordance, and the denied (403) / loading /
  error states are undesigned for this surface. If SHP-02's component already owns its own
  chrome, PGD-05 inherits it and there is nothing to design; if it does not, this is an open
  design gap and must be raised, not filled in.

**Raise before planning:** does SHP-02 ship a self-contained popup component with its own modal
chrome? If yes, PGD-05 is pure wiring plus a row trigger. If no, PGD-05 needs a design decision
that no mockup in `docs/design/mockups/` answers.

## Not specified by the mockup

- The entire member usage popup (above).
- Row click, hover, focus, and selected states on the PGD team table.
- Empty, loading, and error states for the team panel.
- Row truncation, pagination, or "show more" — the panel renders every entry in `people` with no
  cap and no scroll container (unlike the EMD popup's `max-height:340px;overflow:auto`).
- An avatar colour for `QA Engineer` in `docs/design/tokens.md` (the mockup's `#d1495b` is
  untokenised).
- Any sort control — ordering is fixed, not user-selectable.

## Responsive

Desktop-only, consistent with all six mockups (`docs/design/README.md` § Responsive), and a real
gap against the project's stated responsive web target. The enclosing section's
`minmax(min(100%,360px),1fr)` collapses the two-up to one column under ~736px, but this panel's
own internals have no narrow-width variant — and the fixed `1.8fr 1fr 1fr 1fr 1fr` five-column
grid is the most narrow-hostile layout on the page: at 360px each numeric column is ~52px while
`Avg / session` alone needs ~90px for its header. Mobile column collapse, horizontal scroll, or a
card layout is undesigned and must be raised before a mobile breakpoint ships.
