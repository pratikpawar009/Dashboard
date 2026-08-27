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

## Radius

`16px` cards · `20px` pills and chips · `11px` icon tiles · `10px` · `9px` brand mark · `8px`
controls · `6px` chips · `4px` · `2px` dots · `50%` avatars.

## Elevation

One shadow only: `0 1px 2px rgba(15,26,46,.04)` on cards. The design is border-led, not shadow-led.

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
