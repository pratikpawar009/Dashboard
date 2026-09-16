# PGD-02 — Visual spec: Daily token consumption

Design provider: `html-mockup`. Source: `docs/design/mockups/Program Detail.html` (PGD epic per
`docs/design/schema.json`), region `<!-- DAILY TOKEN CONSUMPTION -->` → `<!-- RELEASES VIA HARNESS -->`.
Read during authoring from the instructed local copy `dashboards/Program Detail.html` (byte-identical,
gitignored). Markup is a bundler output — extract per `docs/design/README.md` before diffing.
Tokens: `docs/design/tokens.md`.

## Layout

One `<section>` card on the Program Detail page, sibling to the summary strip above it and the
Releases card below. Inline styles only — no classes, no CSS custom properties.

```
<section>                                   background:#fff; border:1px solid #e9ebef;
                                            border-radius:16px; padding:22px 24px 16px
├─ header row                               display:flex; align-items:flex-start;
│                                           justify-content:space-between; gap:16px;
│                                           flex-wrap:wrap; margin-bottom:6px
│  ├─ <div> titles
│  │   ├─ "Daily token consumption"         font-size:15px; font-weight:700; letter-spacing:-.2px
│  │   └─ "AI token usage per day · {{ tokRangeLabel }}"
│  │                                        font-size:12.5px; color:#7a828f; font-weight:500; margin-top:3px
│  └─ <div> right cluster                   display:flex; align-items:center; gap:16px
│     ├─ stat block                         text-align:right
│     │   ├─ {{ tokTotal }}                 font-size:20px; font-weight:800; letter-spacing:-.5px
│     │   └─ "total · {{ tokAvg }} / day avg"
│     │                                     font-size:10.5px; color:#a2abb8; font-weight:600;
│     │                                     text-transform:uppercase; letter-spacing:.4px
│     └─ segmented toggle                   display:flex; background:#eef0f3; border-radius:10px; padding:3px
│         └─ <sc-for list="{{ tokRanges }}" as="r" hint-placeholder-count="3">
│              <button sc-camel-on-click="{{ r.onClick }}" style="{{ r.style }}">{{ r.label }}</button>
└─ chart area  <div style="margin-top:6px">{{ tokChart }}</div>
```

## Bindings

| Binding | Type | Supplied by |
|---|---|---|
| `{{ tokRangeLabel }}` | string | Client-derived from selected range: `7d`→"last 7 days", `30d`→"last 30 days", `90d`→"last 90 days". Not an API field. |
| `{{ tokTotal }}` | string | API `period_total` (raw int, FR-2) **formatted client-side** — see § Formatting responsibility. |
| `{{ tokAvg }}` | string | API `avg_per_day` (raw int, FR-2) **formatted client-side**. Rendered inside the fixed literal `total · {{ tokAvg }} / day avg`. |
| `{{ tokRanges }}` | 3-entry array of `{label, onClick, style}` | Client-owned. `label` ∈ `"7D" \| "30D" \| "90D"`; `onClick` sets range state and refetches; `style` is `segBtn(active)` output. |
| `{{ tokChart }}` | rendered SVG node | Client chart component over API `points[] = {date, tokens:int}`. |

`{{ tokRangeLabel }}`, the button labels, and the range→label map are presentation constants owned by
the component — the API returns no label strings for this section.

## Range toggle

Mockup source (`makeRanges` / `segBtn`), initial state `tokRange: '30d'`:

| Button label | Range param |
|---|---|
| `7D` | `7d` |
| `30D` | `30d` |
| `90D` | `90d` |

`segBtn(active)` — the only difference between states is three properties:

| Property | Selected | Unselected |
|---|---|---|
| `background` | `#fff` | `transparent` |
| `color` | `#151a22` | `#7a828f` |
| `box-shadow` | `0 1px 2px rgba(0,0,0,.08)` | `none` |

Shared by both states: `border:none; font-family:inherit; font-size:12px; font-weight:700;
padding:6px 13px; border-radius:8px; cursor:pointer`. The track behind them is `background:#eef0f3;
border-radius:10px; padding:3px`.

Accessibility (NFR-008, not in the mockup — the mockup emits bare `<button>`s): the group is a
single-select control, so render it as `role="group"` with an accessible name and
`aria-pressed`/`aria-current` on the active button. Selection must not be signalled by colour alone.

## Chart area

The mockup's `areaChart(vals, days, color)` renders an inline `<svg>` — geometry worth preserving:

- `viewBox 0 0 1000 240`, `style="width:100%;height:240px;display:block"`, `preserveAspectRatio:none`.
- Padding `padL/padR 6`, `padT 16`, `padB 30`; y-scale max is `max(vals) * 1.12` (headroom).
- 4 horizontal gridlines at 25/50/75/100% of plot height, `stroke:#eef0f3`, `stroke-width:1`.
- Area fill: vertical `linearGradient` from `stopOpacity 0.24` to `0`, in the program-type accent colour.
- Line: `stroke-width:2.6`, `stroke-linecap/linejoin:round`, no fill.
- Last point marker: `circle r=4.5`, `fill:#fff`, stroke = accent, `stroke-width:2.6`.
- X tick labels: 7 ticks for the 7D range, 6 otherwise; `font-size:13`, `font-weight:600`,
  `fill:#9aa2ae`, `font-family:'Plus Jakarta Sans', sans-serif`; first anchored `start`, last `end`,
  rest `middle`; format `"Mon D"` (e.g. `Jul 15`).

Accent colour is the program-type colour `t.c` already resolved for the page header
(`Migration #2a6fdb`, `Greenfield feature development #1f8a5b`, `Brownfield feature development
#7c5cff`, `Maintenance #c08a1e`) — the chart must reuse the page's existing type colour, not pick its own.

**`genDaily()` and the seeded RNG are demo data — do not port them.** `genDaily(days, mean, seed)` is
an LCG with a trend/weekend/noise shape that exists only to populate the canvas. The real component
plots the API's `points[]` in date order. `areaChart()`'s *geometry* is the spec; its *input* is not.

## States

`hint-placeholder-count="3"` on the `tokRanges` `sc-for` states that the canvas renders exactly 3
placeholder buttons — it is a fixed-arity control, not a data-driven list. There is no
`hint-placeholder-count` on the chart or the stat block, so the mockup provides no explicit skeleton
for them. Derived states (PRD § Screen inventory):

| State | Rendering |
|---|---|
| Populated | As specified above. |
| Loading | Card chrome, title, subtitle and all 3 range buttons stay mounted and interactive-disabled; stat block and chart area show a skeleton at the chart's fixed 240px height so the card does not reflow on range switch. |
| Empty | Never a "no data" card: the API zero-pads every missing day, so an empty program yields a full-length all-zero `points[]`, `period_total: 0`, `avg_per_day: 0`. Render the flat-zero line. Guard the chart's `max(vals) * 1.12` y-scale against an all-zero series (division by zero) with a minimum axis max. |
| Error | Card chrome + title retained, chart area replaced by an inline error with retry. Range buttons stay usable. |

## Formatting responsibility

**The frontend owns magnitude formatting for this section.** A named, deliberate departure from
`docs/design/README.md`'s "values arrive pre-formatted" decision, scoped to this endpoint only.

The mockup computes both stat values itself:

```js
const fmtM = n => n >= 1000 ? (n / 1000).toFixed(2) + 'B' : n.toFixed(1) + 'M';
const tokTotal = fmtM(tokSum);
const tokAvg   = fmtM(tokSum / tokDays);
```

The binding user decision (PRD § Addressing Research Conditions C-4, FR-2/FR-3) requires the API to
return **raw integers** for `period_total`, `avg_per_day`, and `points[].tokens`. So unlike every other
value on this page, these arrive unformatted and the component must format them.

Implementation obligations:

1. `DailyTokenTrendChart` implements its own `formatTokens(n: number): string` and applies it to
   `period_total` → `{{ tokTotal }}` and `avg_per_day` → `{{ tokAvg }}`. Do not call the API's
   `format_number()` equivalent — it is not in the response.
2. **`fmtM`'s thresholds are the canvas's own demo-data scale and must be reconciled, not copied.**
   `fmtM` assumes its input is already *in millions*: it emits `"M"` below 1000 and divides by 1000
   for `"B"`. The API returns a raw token count. Feeding a raw count into `fmtM` verbatim would label
   1,200 tokens as `"1.20B"`. Pick the unit ladder against real token magnitudes in
   `program_token_series` and state the chosen thresholds in the component.
3. `points[].tokens` is also raw — any value shown in a tooltip or axis label needs the same
   formatter; the plotted geometry uses the raw numbers.

## Responsive

The mockups are **desktop-only** despite the project's responsive web target
(`docs/design/README.md`), so the mockup settles nothing below desktop width. Implementation
decisions, not design facts:

- The header row already carries `flex-wrap:wrap`, so the right cluster (stat block + toggle) wraps
  below the titles on narrow viewports without extra work — verify the wrapped order reads sensibly.
- The chart is `width:100%` with a fixed `height:240px` and `preserveAspectRatio:none`, so it stretches
  rather than scales; at phone widths the 6–7 date ticks will collide. Decide tick thinning (or a
  reduced tick count) at implementation time.
- The 3-button toggle at `padding:6px 13px` is below the 44px touch-target guideline; decide whether
  to grow it on coarse pointers.
