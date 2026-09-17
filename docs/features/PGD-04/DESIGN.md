# DESIGN — PGD-04 Commands executed panel

**Provider**: `html-mockup` · **Source**: `docs/design/mockups/Program Detail.html` (PGD epic, per `docs/design/schema.json`), `<!-- COMMANDS -->` section
**Iteration**: 0 · **Status**: extracted from the authored mockup — no new design work

The mockup is authored, not generated here. It is a bundler output — see `docs/design/README.md`
for the decode snippet before diffing or grepping.

**PGD-04 ships backend-only** (PRD § Scope, research condition C-5). No React component ships:
`apps/web/src` contains no commands component, and no RTM story owns one. This file therefore
records the mockup as the **binding contract the API must satisfy** — which fields the template
consumes, which arrive pre-formatted, and what the placeholder state implies. Rendering is
deferred to a follow-on frontend story that must be scoped against this contract.

## Screen: Commands executed panel

Embedded section on the existing Program Detail page. No route of its own. Left card of the
`COMMANDS + TEAM` two-up section (`repeat(auto-fit,minmax(min(100%,360px),1fr))`, `gap:16px`),
below the releases list (PGD-03); the right card is Project team (out of scope here).

### Container

`background:#fff · border:1px solid #e9ebef · border-radius:16px · overflow:hidden`
Header block `padding:18px 20px 14px` with `border-bottom:1px solid #f0f1f4`; body `padding:8px 20px 16px`.

### Header

| Element | Spec | Binding |
|---|---|---|
| Title | `15px/700`, `letter-spacing:-.2px` | literal `Commands executed` |
| Subtitle | `12.5px/500`, `#7a828f`, `margin-top:3px` | `Activity by Claude Code command · {{ cmdRangeLabel }}` |
| Total value | `22px/800`, `letter-spacing:-.5px` | `{{ cmdTotal }}` |
| Total label | `10.5px/600`, `#a2abb8`, uppercase, `letter-spacing:.5px` | literal `total runs` |
| Range chips | `sc-for {{ cmdRanges }}` (`hint-placeholder-count="3"`), pill group `background:#eef0f3 · border-radius:10px · padding:3px` | `{{ r.label }}`, `{{ r.style }}` |

`cmdRangeLabel` is a fixed map, mockup L740 — `7d → "last 7 days"`, `30d → "last 30 days"`,
`90d → "last 90 days"`. Chip labels are `7D` / `30D` / `90D`; the active chip is
`background:#fff · color:#151a22 · box-shadow:0 1px 2px rgba(0,0,0,.08)`, inactive is
transparent `#7a828f` (`segBtn()`). Range state and chip styling are client-owned — the API
supplies neither.

### Row list

`<sc-for list="{{ commands }}" as="c" hint-placeholder-count="6">`. Each row
`padding:13px 0`, `border-bottom:1px solid #f4f5f7`, `flex-direction:column`, `gap:8px`:

| Element | Spec | Binding |
|---|---|---|
| Command chip | `<code>` `12.5px/600` JetBrains Mono, `color:#2a3441`, `background:#f2f4f7`, `padding:3px 8px`, `border-radius:6px`, `white-space:nowrap` + ellipsis overflow | `{{ c.cmd }}` — **wire name is `command`** (see below) |
| Count | `13px/700`, `flex:none` | `{{ c.count }}` |
| Count unit | `10.5px/600`, `#a2abb8`, `margin-left:3px` | literal `runs` |
| Bar track | `height:6px · border-radius:4px · background:#eef0f3 · overflow:hidden` | — |
| Bar fill | inline style, wholly server-supplied | `{{ c.barStyle }}` |

Ordering is descending by count (the mockup's `cmdMix` weights are authored 0.30 → 0.08).

### Bar formula

Mockup L756:

```
height:100%;width:${round(count / max(counts in this range) * 100)}%;background:${t.c};border-radius:4px
```

**Max-of-range, not share-of-total** — the top command always renders `width:100%`. This is
PGD-04-FR-3 and matches `CommandEntry`'s existing `bar_style` contract (ADR-0009).
`t.c` is the program-type colour from `docs/design/tokens.md` § Program type colors, via the
mockup's `tMap` with `|| tMap['Migration']` as the fallback for an unrecognised type — the same
derivation PGD-03 uses for `tagColor`/`tagBg`.

### Wire names — mockup local vs. shipped field

The mockup's generator names its loop variable `cmd`; the shipped wire field is `command`,
already fixed by SHP-02's `CommandEntry` in `services/api/app/schemas/personal_usage.py`, which
PGD-04 reuses verbatim (PRD constraint, C-3). Document and implement against `command`; a future
renderer binds `c.command` where the mockup reads `c.cmd`.

| Mockup binding | Wire field (`CommandEntry` / `CommandsPanel`) | Type |
|---|---|---|
| `c.cmd` | `command` | `str`, pre-formatted (leading `/`, see below) |
| `c.count` | `count` | **raw int** — the bar formula's own input |
| `c.barStyle` | `bar_style` (alias `barStyle`) | `str`, ready-to-bind CSS |
| `cmdTotal` | `total_runs` | `str`, pre-formatted |
| `commands` | `items` | ordered array |

### Pre-formatted values

Per `docs/design/README.md` § "Values arrive pre-formatted", the panel formats nothing:

- `command` renders exactly as sent, including its leading `/`. The mockup composes
  `'/' + c.cmd` (L755) because its mock generator stores bare names, but **real ingested data
  already carries the slash** — `docs/activity/activity.jsonl` records `"command":"/arh-init"`,
  and `ingest_files.py:72` applies no format constraint. So the API passes the stored
  `usage_events.command` through **verbatim** and MUST NOT synthesize a leading `/`; doing so
  would yield `//arh-init`. Verified 2026-09-17 against real ingest data, not inferred from the
  mockup's generator.
- `total_runs` is a string, not a number.
- `count` is the documented exception: a raw int, because it is the bar formula's numerator.
- `cmdRangeLabel` is derived client-side from the selected range, not returned by the API.

### CSS-bearing bindings

`c.barStyle` is a complete inline-style string consumed directly in `style=`, per
`docs/design/README.md` § "The templates also bind presentation". This is already the settled
project position for this exact field (`CommandEntry.bar_style`, ADR-0009) — PGD-04 inherits it
rather than re-deciding.

### Empty / placeholder state

`hint-placeholder-count="6"` renders six placeholder rows in the canvas; the generator's `cmdMix`
has exactly six entries. That is a canvas rendering hint, **not** a contract that the API returns
six rows — no minimum or maximum row count is specified.

The mockup shows **no empty-state copy, no loading state, no error state, and no zero-row
rendering**. PGD-04-FR-1's `200 {total_runs: "0", items: []}` for a quiet or unknown program is
therefore an API-level contract the design does not illustrate: the header would render `0`
beside "total runs" over an empty row list. Empty-state copy is undesigned and must be raised
before a renderer ships it, not invented.

## Not specified by the mockup

- Empty, loading, and error states (above).
- Row truncation / "show more" — the panel renders every entry in `commands` with no cap.
- Any per-row interaction. The rows carry no `sc-camel-on-click`; only the range chips are
  interactive.

## Responsive

Desktop-only, consistent with all six mockups (`docs/design/README.md` § Responsive). The
enclosing section's `minmax(min(100%,360px),1fr)` collapses the two-up to one column under
~736px, but the panel's own internals have no narrow-width variant.
