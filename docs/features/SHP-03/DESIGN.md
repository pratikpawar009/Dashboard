# DESIGN: SHP-03 — Personal session-wise usage list (paginated)

**Provenance**: hand-authored 2026-09-18 during `/arh-plan-requirements` Phase 2. `ux-agent` is not
installed in this repo — `.claude/agents/` has no `ux-agent.md` — the same gap SHP-01, PGD-01,
OVW-01, OVW-05, OVW-04 and SHP-04 each hit and recorded in their own `DESIGN.md`. This is the
**seventh** occurrence; OVW-01 reclassified it from surprise to standing condition and SHP-04
carried it forward. Nothing new to add — it remains a carry-forward item for a decision on whether
to install the agent. This file was written directly from the decoded design source, not generated.
It is a **pre-implementation spec**: neither the route nor the component exists. **The mockup, not
this file, is the source of truth on any disagreement.**

**Design source**: `docs/design/mockups/{Architect,Developer,Product Manager} Dashboard.html`.
SHP has no entry in `docs/design/schema.json` → `designSystem.pages.features`; this story's surface
is reached through its downstream consumers ARC-01 / DEV-01 / PMD-01, whose epics do map there.
Claude Design canvas exports — decoded per `docs/design/README.md` § "These are bundler outputs".
Each decode is 1,100 lines. Line references below are into that decode.

**Region identity verified, not assumed**: the three decoded files are *not* identical overall, but
the `<!-- MY SESSIONS TABLE -->` region (L482–514) is byte-identical across all three
(`md5 = cca5d6b80c01008fcbeffc8ef988ecbc` for each). Treated as one screen, not three.

## Scope

This story owns the `MY SESSIONS TABLE` section only (L482–514). The decoded document's section
comments are `BRAND BAR`, `HEADER`, `CONTENT`, `MY USAGE`, `YOUR DAILY TOKEN CONSUMPTION`,
`YOUR COMMANDS`, `MY SESSIONS TABLE`, `PROGRAM SUMMARY`, `ARTIFACTS + RELEASES`, `PROJECT TEAM`,
`COMMANDS + COMPLIANCE`, `CONSTITUTION`, `MEMBER COMMAND POPUP`.

| Screen | Region | Component | Mockup anchor |
|---|---|---|---|
| Your session-wise usage | embedded panel on `/architect`, `/developer`, `/product-manager` (ARC-01/DEV-01/PMD-01) | `SessionsTable` (new) | `<!-- MY SESSIONS TABLE -->` L482–514 |

Explicitly **not** in scope: `PROGRAM SUMMARY` (L516+), `ARTIFACTS + RELEASES` (SHP-04 owns the
artifacts half), and the parent dashboard page composition, which belongs to ARC-01/DEV-01/PMD-01.

## Anatomy

A single `<section>` card — `background:#fff`, `border:1px solid #e9ebef`, `border-radius:16px`,
`overflow:hidden` — with four stacked bands:

### 1. Header band (L484–490)

`padding:18px 22px 14px`, flex row, `border-bottom:1px solid #f0f1f4`.

| Element | Binding | Style |
|---|---|---|
| Title | static `"Your session-wise usage"` | `15px / 700 / letter-spacing:-.2px` |
| Subtitle | `Your recent sessions on {{ prog.name }}` | `12.5px / 500 / #7a828f`, `margin-top:3px` |

The subtitle interpolates `prog.name` — the **parent page's** program context, not this story's
payload. SHP-03's API is a cross-program aggregate with no `program_id` (§ Divergences, D-3).

### 2. Column header row (L491–493)

`display:grid; grid-template-columns:2.6fr 1fr 1.1fr`, `padding:11px 22px`, `background:#fafbfc`,
`border-bottom:1px solid #f0f1f4`. Labels are `10.8px / 700 / letter-spacing:.5px / #a2abb8`,
`text-transform:uppercase`.

| Column | Label | Alignment |
|---|---|---|
| 1 | `Session` | left |
| 2 | `Duration` | right |
| 3 | `Tokens` | right |

**Three columns, not five.** The story's AC-1 names five fields (name/description, identifier,
date, duration, tokens). The mockup renders three columns, with identifier and date folded into a
sub-line under the session name (§ Divergences, D-1).

### 3. Scroll body (L494–504)

`max-height:296px; overflow:auto` wrapping `<sc-for list="{{ sessions }}" as="s"
hint-placeholder-count="20">`. The placeholder count of **20** corroborates `page_size = 20` as the
default independently of the generator constant — this is the loading-state skeleton row count.

Each row repeats the header's `2.6fr 1fr 1.1fr` grid, `padding:14px 22px`, `align-items:center`,
`border-bottom:1px solid #f4f5f7`.

| Cell | Binding | Style |
|---|---|---|
| Session title | `{{ s.title }}` | `13.5px / 600`, single-line: `white-space:nowrap; overflow:hidden; text-overflow:ellipsis` on a `min-width:0` parent |
| Session meta | `{{ s.meta }}` | `11.5px / 500 / #9aa2ae`, `margin-top:3px`, **`font-family:'JetBrains Mono', monospace`** |
| Duration | `{{ s.duration }}` | `13px / 500 / #4a5261`, right-aligned |
| Tokens | `{{ s.tokens }}` | `13.5px / 700`, **monospace**, right-aligned |

Four bindings per row: `title`, `meta`, `duration`, `tokens`. No other field is bound — anything the
API returns beyond these is unrendered by this panel.

### 4. Footer / pagination band (L505–513)

`padding:14px 22px`, flex row `justify-content:space-between`, `gap:12px`, `flex-wrap:wrap`,
`border-top:1px solid #f0f1f4`.

| Element | Binding | Notes |
|---|---|---|
| Range text | `{{ sesRangeText }}` | `12px / 500 / #9aa2ae`. Format: `"1–20 of 63 sessions"` — en-dash `–`, not a hyphen |
| Prev button | `{{ sesPrev }}` / `{{ sesPrevStyle }}` | glyph `‹` |
| Page buttons | `<sc-for list="{{ sesPages }}" as="p" hint-placeholder-count="4">` → `{{ p.label }}`, `{{ p.onClick }}`, `{{ p.style }}` | one button per page |
| Next button | `{{ sesNext }}` / `{{ sesNextStyle }}` | glyph `›` |

Button base style (L945): `min-width:30px; height:30px; padding:0 8px; border-radius:8px;
font-size:12.5px; font-weight:600; cursor:pointer; flex centred`. Active page (L949):
`border:1px solid #2a6fdb; background:#2a6fdb; color:#fff`.

Per `docs/design/README.md` § "The templates bind CSS as well as data", `sesPrevStyle`,
`sesNextStyle` and `p.style` are bound *styles*, not just data — the disabled/active appearance is
supplied with the value rather than computed by the component.

## Value formats — read from the generator

The mockup's own sample-data generator (L918–934) is the authoritative statement of each value's
shape. Per `docs/design/README.md` § "Values arrive pre-formatted", these are the wire formats, not
display transforms the component applies.

| Field | Generator expression | Example | Wire type |
|---|---|---|---|
| `title` | `sesTitles[i % len]` | `"Refactor auth middleware"` | string, verbatim |
| `meta` | `'S-' + n + ' · ' + mo + ' ' + day + ', 2026'` | `"S-1088 · Jul 5, 2026"` | **pre-joined string** |
| `duration` | `Math.floor(mins/60) + 'h ' + String(mins%60).padStart(2,'0') + 'm'` | `"2h 07m"` | pre-formatted string |
| `tokens` | `tk >= 1 ? tk.toFixed(1)+'M' : Math.round(tk*1000)+'K'` | `"1.2M"` / `"840K"` | pre-formatted string |

Three details the formats pin down that prose would lose:

1. **`meta` separator is `·` (U+00B7 middle dot) with a space on each side**, and the session
   identifier carries an `S-` prefix. The year is present (`", 2026"`) — unlike
   `/api/overview/program-detail/{id}/releases`, whose `date` is `"Jul 15"` with no year.
2. **`duration` zero-pads minutes but not hours** — `"2h 07m"`, never `"2h 7m"`, and never `"02h"`.
3. **`tokens` switches unit at 1M** — one decimal above (`"1.2M"`), a whole-number `K` below
   (`"840K"`). No `B` tier appears in the generator and no raw-int form is rendered.

## Divergences from the story / PRD

Recorded so the PRD's wire contract is not read as contradicted by the mockup. The mockup wins on
shape; these are the points where it constrains the API more tightly than the story anticipated.

**D-1 — identifier and date are not separately bound.** Story AC-1 lists five fields; the mockup
binds four, folding `session_identifier` and `started_at` into the single pre-joined `s.meta`
string. Research risk #1 anticipated a *name/description* collapse; the real collapse is wider. The
API composes `meta` server-side per this file's format table — the component must not be given the
parts and asked to join them, since every other value on this panel arrives pre-formatted.

**D-2 — the mockup paginates client-side; the API does not.** The generator materialises all 63
rows and `sessions` is `sesGen.slice(sesPage * 20, …)` (L939) with `sesRangeText` and `sesPages`
derived from `sesGen.length`. SHP-03 specifies a **server**-paginated endpoint. This is a canvas
prototyping artefact, not a design instruction: a canvas export has no server to call. The
server-paginated contract stands; the component binds the same four fields per row and gets its
range/page metadata from the API's `total` instead of an in-memory array length. Rendering is
unaffected. Flagged because a literal reading of the mockup would wrongly imply fetch-all.

**D-3 — `prog.name` in the subtitle has no source in this story's payload.** The header interpolates
a program name, but SHP-03's endpoint is a cross-program aggregate with no `program_id` in request
or response (inherited from SHP-02's `/api/personal-usage/{user_id}` contract). The parent
dashboard page (ARC-01/DEV-01/PMD-01) supplies `prog.name` from its own program context. SHP-03
must **not** add a program field to satisfy this binding.

**D-4 — no empty state is drawn.** AC-5 requires zero sessions to render as an empty list rather
than an error, but the mockup's generator always produces 63 rows, so no empty-state markup exists.
Nothing to copy. Raised in the PRD's open questions territory rather than invented here: the
component needs an empty-state treatment the design source does not specify.

**D-5 — no 403 state is drawn.** AC-4's cross-user denial has no mockup representation either; the
panel only ever renders its own user's sessions. Same handling as D-4.

## Tokens used

Every value below resolves to an existing entry in `docs/design/tokens.md` / `schema.json` —
no new token is introduced by this story.

| Token | Value | Used for |
|---|---|---|
| `primary` | `#2a6fdb` | active page button background + border |
| `ink` | `#0f1a2e` | (inherited body text) |
| `text-700` | `#5b6472` | — (subtitle uses `#7a828f` = `text-600`) |
| `text-600` | `#7a828f` | header subtitle |
| `text-400` | `#9aa2ae` | row meta line, range text |
| `text-300` | `#a2abb8` | column header labels |
| `border-100` | `#e9ebef` | card border |
| `surface-200` | `#f0f1f4` | band dividers |
| `surface-100` | `#f4f5f7` | row divider |
| `surface-50` | `#fafbfc` | column header background |

`#4a5261` (duration cell) does **not** appear in `docs/design/tokens.md`'s colour list — it sits
between `ink` and `text-700`. Carry-forward: either add it as a token or map the duration cell to
`text-700` during implementation. Not decided here.

Monospace faces (`'JetBrains Mono'`) on the meta and tokens cells follow the same numeric/identifier
convention the other panels use.

## Accessibility

The mockup is a canvas export and carries no semantics — the region is `<div>`-grid throughout, with
no `<table>`, no header association, and buttons whose only content is `‹` / `›` glyphs. The PRD's
NFR targets WCAG AA, so implementation must add what the source omits rather than copy it:

- The grid is a genuine data table — render `<table>` semantics (or an ARIA grid) so the `Session` /
  `Duration` / `Tokens` headers associate with their cells.
- `‹` and `›` buttons need accessible names ("Previous page" / "Next page"); the glyph alone is not
  one. Page-number buttons need the current page marked (`aria-current="page"`).
- The active-page indicator is colour-only in the mockup (blue fill). `aria-current` carries it
  non-visually.
- The `max-height:296px; overflow:auto` scroll body needs to be keyboard-reachable.
- Truncated session titles (`text-overflow:ellipsis`) must keep the full text available.

Desktop-only source, per `docs/design/README.md`; the responsive behaviour of the footer band
(`flex-wrap:wrap` is the only hint) is not specified by the design and is an implementation
decision.
