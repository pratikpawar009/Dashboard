# DESIGN — PGD-03 Releases list (paginated)

**Provider**: `html-mockup` · **Source**: `docs/design/mockups/Program Detail.html` (PGD epic, per `docs/design/schema.json`)
**Iteration**: 0 · **Status**: extracted from the authored mockup — no new design work

The mockup is authored, not generated here. This file records what the extracted markup
specifies, so implementation has a readable contract. It is a bundler output — see
`docs/design/README.md` for extraction before diffing or grepping.

## Screen: Releases panel

Embedded section on the existing Program Detail page. No route of its own. Sits between the
token-trend chart (PGD-02) and the Commands + Team section.

### Container

`background:#fff · border:1px solid #e9ebef · border-radius:16px · overflow:hidden`

### Header

Flex row, `padding:18px 22px 16px`, `border-bottom:1px solid #f0f1f4`, wraps at narrow widths.

| Element | Binding | Type |
|---|---|---|
| Title | `Releases via Harness` | static · 15px/700, `letter-spacing:-.2px` |
| Subtitle | `Releases shipped with Harness · {{ relRangeLabel }}` | 12.5px/500, `#7a828f` |
| Stat value | `{{ relTotal }}` | 20px/800, right-aligned |
| Stat caption | `releases shipped` | static · 10.5px/600 uppercase, `#a2abb8` |
| Range switcher | `{{ relRanges }}`, `hint-placeholder-count="3"` | 3 buttons — 7d / 30d / 90d |

`relRangeLabel` is prose, not a code: `last 7 days` / `last 30 days` / `last 90 days`.

The switcher is **independent of PGD-02's chart switcher** — changing the range here refetches
only this panel. Track `#eef0f3`, `border-radius:10px`, `padding:3px`; each button carries its own
`{{ r.style }}` and `{{ r.onClick }}`.

### Column headers

`display:grid · grid-template-columns:0.9fr 1.5fr 1fr 0.8fr 0.8fr · padding:11px 22px`
`background:#fafbfc`, 10.8px/700 uppercase, `color:#a2abb8`, `letter-spacing:.5px`.

`Version` · `Release` · `Date` · `Stories` (right) · `PRs merged` (right)

### Row list

Scroll container: `max-height:296px · overflow:auto` — this is the fixed-height scroll that
story AC-7 / FR-PD-10 describe. The page itself does not grow with the row count.

`<sc-for list="{{ releases }}" as="r" hint-placeholder-count="6">` — six placeholder rows are the
loading/empty state.

Each row reuses the header's grid, `padding:13px 22px`, `border-bottom:1px solid #f4f5f7`.

| Cell | Binding | Rendering |
|---|---|---|
| Version | `{{ r.ver }}` | `<code>` 12px/700 JetBrains Mono, `color:{{ r.tagColor }}`, `background:{{ r.tagBg }}`, `padding:3px 9px`, `border-radius:6px` |
| Release | `{{ r.dot }}` + `{{ r.label }}` | 7px circle in `r.dot`, then 13.5px/600 label, ellipsis on overflow |
| Date | `{{ r.date }}` | 12.5px/500 JetBrains Mono, `#5b6472` |
| Stories | `{{ r.stories }}` | 13px/600, right |
| PRs merged | `{{ r.prs }}` | 13px/600 JetBrains Mono, right |

### Release-kind vocabulary

Closed 3-entry set. `label` and `dot` ship pre-formatted from the API.

| Label | Dot |
|---|---|
| `Feature release` | `#1f8a5b` |
| `Patch release` | `#2a6fdb` |
| `Hotfix` | `#d1495b` |

The mockup's `genReleases` `kinds` array holds four elements because `Feature release` appears
twice — that weights it 2-in-4 in the sample-data picker and is not a fourth kind.

### Pre-formatted values

Per `docs/design/README.md` § "Values arrive pre-formatted", the server sends display-ready
strings; the panel formats nothing:

- `r.date` → `"Jul 15"` — month abbreviation + day, **no year**.
- `r.stories`, `r.prs`, `relTotal` → strings, not numbers.

### CSS-bearing bindings

`r.dot`, `r.tagColor`, `r.tagBg` are colour literals consumed directly in `style=`. In the mockup
`tagColor`/`tagBg` come from the *program's* theme and are identical on every row — see the PRD's
functional requirements for whether they are hoisted to the response top level or repeated per row.

## Not specified by the mockup

The mockup renders a single static page of sample rows. It shows no pagination control, no
explicit empty-state copy, and no error state. Those are the PRD's to define — `offset`/`limit`
exist in the API contract but have no rendered affordance in the design.

## Responsive

Desktop-only, consistent with the other five mockups (`docs/design/README.md`). The header row
carries `flex-wrap:wrap`, but the 5-column grid has no narrow-width variant.
