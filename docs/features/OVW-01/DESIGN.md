# DESIGN: OVW-01 — Org summary cards + adoption indicator

**Provenance**: hand-authored 2026-09-09 during `/arh-plan-requirements` Phase 2. `ux-agent` is not
installed in this repo — `.claude/agents/` has no `ux-agent.md` — the same gap PGD-01 and SHP-01 both
hit and recorded in their own `DESIGN.md` files. This is the third occurrence, so it is now a
standing condition rather than a surprise; it is carried forward for a decision on whether to install
the agent. This file was therefore written directly from the design source instead of generated. Like
PGD-01's it is a **pre-implementation spec**: no code exists for these regions yet. **The mockup, not
this file, is the source of truth on any disagreement.**

**Design source**: `dashboards/CIO Portfolio Dashboard.html` — read from the repo-root `dashboards/`
directory per a standing user instruction that supersedes the `docs/design/mockups/` path in
`CLAUDE.md` and `docs/design/schema.json` (which maps the `OVW` epic to this mockup). The two copies
are byte-identical: 6 files, matching sizes, `diff -rq` clean, verified 2026-09-09. A Claude Design
canvas export — it must be decoded before the markup is readable; `docs/design/README.md` § "These
are bundler outputs" carries the procedure. Decoded document: 39,478 characters. Bindings and literal
copy below are quoted from that decode, not from the research report.

**Scope**: two of the mockup's eight regions. The decoded document's section comments are
`BRAND BAR`, `HEADER`, `CONTENT`, `ORG SUMMARY`, `ORG MONTHLY TOKEN COST BAR CHART`,
`MONTHLY ACTIVE USERS BY ROLE`, `PROGRAM ADOPTION HEALTH`, `PROGRAM LEADERBOARD`. **This story owns
`ORG SUMMARY` and `PROGRAM ADOPTION HEALTH` only.** The token-cost bar chart, MAU-by-role and
leaderboard belong to OVW-02/03/04 — do not build them here.

---

## Region 1 — `ORG SUMMARY` (1,558 chars decoded)

### Literal copy — static, never bound

| Element | Exact text |
|---|---|
| Section heading | `Organization summary` |
| Heading suffix | `— all programs · To date` |

Both are static copy. The suffix mirrors PGD-01's `— to date`, which
`apps/web/src/components/ProgramSummaryCards.tsx:19-21` records as "static copy … the heading never
varies with props". **There is no range toggle and no as-of timestamp** here either — see § The
freshness decision below.

### Repeat construct

```html
<sc-for list="{{ orgKpis }}" as="k" hint-placeholder-count="5">
```

`hint-placeholder-count="5"` is a **contract, not a sample size** — PGD-01 established that reading
(its `LOADING_PLACEHOLDER_COUNT = 7` comment cites the mockup's own attribute as the contract). The
loading state renders exactly 5 placeholder cards at the populated card's geometry with text
suppressed.

### Per-card bindings — four fields, not three

| Binding | Renders as | Notes |
|---|---|---|
| `k.glyph` | icon, its own styled container | server-owned presentation constant (ADR-0007) |
| `k.value` | `font-size:25px; font-weight:800; letter-spacing:-.8px; line-height:1; color:#0f1a2e` | the primary metric, pre-formatted server-side |
| `k.label` | `font-size:12px; color:#7a828f; font-weight:500; margin-top:7px` | descriptive label, server-owned constant |
| `k.sub` | `font-size:11px; color:#1f8a5b; font-weight:600; margin-top:5px` | **optional**, `sc-if`-guarded — see below |

```html
<sc-if value="{{ k.sub }}" hint-placeholder-val="x">
  <div style="font-size:11px;color:#1f8a5b;font-weight:600;margin-top:5px">{{ k.sub }}</div>
</sc-if>
```

**`k.sub` is the one field this story nearly shipped without.** The PRD's `OVW-01-FR-1` originally
specified `{glyph, value, label}`, inherited from `program-detail-api`'s card shape. That precedent is
a genuinely three-field one — the Program Detail mockup binds only `s.glyph`/`s.label`/`s.value`, and
`ProgramSummaryCardData` (`apps/web/src/types/programDetail.ts:24-28`) matches it exactly — but **this
mockup binds a fourth**. FR-1 was corrected on 2026-09-09 after direct extraction.

Because the `sc-if` omits the element when `sub` is falsy, **`null` for all five cards is a fully
conformant render**. The mockup establishes that the field exists and is optional; it says nothing
about what any card's `sub` should contain. Ship `null` until a requirement defines otherwise, and do
**not** invent copy for it — `CLAUDE.md` § Design system forbids exactly that.

### States

| State | Rendering |
|---|---|
| Populated | 5 cards in the backend's array order — order is the contract (ADR-0007), never re-sorted client-side |
| Loading | 5 placeholder cards (`hint-placeholder-count="5"`), same geometry, text suppressed |
| Empty (fresh DB, AC-2) | 5 cards with all-zero values — **not** a distinct empty-state screen. The mockup has no empty variant, so the zero values simply flow through the populated layout |
| Error (403 non-CIO, AC-3) | per `api-conventions` error shape; the mockup shows no error region, so do not invent one |

---

## Region 2 — `PROGRAM ADOPTION HEALTH` (1,587 chars decoded)

### Literal copy

| Element | Exact text |
|---|---|
| Section heading | `Adoption Level` |

Note the PRD's Screen inventory calls this region "Adoption level indicator" and refers to a
`PROGRAM ADOPTION HEALTH` headline. The section *comment* is `PROGRAM ADOPTION HEALTH`; the
**rendered heading is `Adoption Level`**. Use the rendered text.

### Bindings

| Binding | Purpose |
|---|---|
| `adoptionHeadline` | the headline string — pre-formatted server-side |
| `adoptionPct` | the percentage, bound separately from the headline |
| `adoptionBarUsing` | adopted segment of the 2-segment bar |
| `adoptionBarNot` | not-yet-adopted segment |
| `adoptionLegend` | legend collection, `sc-for … hint-placeholder-count="2"` |
| `h.color`, `h.count`, `h.label` | per legend entry |

`hint-placeholder-count="2"` fixes the legend at exactly two entries (adopted / not-yet-adopted).

### The CSS-on-the-wire decision

`docs/design/README.md` records that these templates **bind CSS as well as data** —
`adoptionBarUsing`/`adoptionBarNot` are segment widths and `h.color` is a legend swatch colour, all
of which the canvas expects as bound values. The PRD's **`OVW-01-FR-2`** deliberately declines to put
inline CSS on the wire: the API returns data and the **client derives** bar widths and legend colours.

That is a conscious divergence from the mockup's binding style, not an oversight. It keeps the
response a data contract rather than a styling channel, and it matches how `program-detail-api`
already behaves. Recorded here so an implementer diffing this file against the mockup sees the
divergence explained rather than treating it as a defect to "fix".

### States

| State | Rendering |
|---|---|
| Populated | headline + 2-segment bar + 2-entry legend |
| Empty (`programs_total = 0`) | `adoption_percent` is `null` → `0/0` headline and a flat bar, per `OVW-01-FR-4`. No invented empty-state copy |
| Error (403 non-CIO, AC-3) | as Region 1 |

---

## The freshness decision (AC-6) — nothing renders

Clarification **C-1** resolved on 2026-09-09: **AC-6 is backend-only and no freshness timestamp
appears anywhere on this page.** Three strands of evidence, all verifiable:

1. The decoded mockup contains no as-of / last-updated / freshness string at all. The only `UTC`
   matches in the raw file are random substrings inside its base64 asset payload — inspected, not
   assumed.
2. PGD-01 decided identically for the analogous component:
   `apps/web/src/components/ProgramSummaryCards.tsx:19-21` — "no as-of timestamp anywhere in this
   story".
3. `CLAUDE.md` § Design system: "If a story seems to need something the mockups do not show, stop and
   raise it. **Do not design it.**"

**AC-7 is unaffected and still required**: the endpoint must still read `last_successful_run_at`
through the `freshness-api` accessor and raise "ingestion job may not have run yet" when no
`system_metadata` `ingestion` row exists. That is backend behaviour the mockup has no opinion about.

---

## Form factors

**Desktop-only.** `docs/design/README.md` notes all six mockups are desktop-only despite the
project's responsive web target (`CLAUDE.md` § Target platforms: "Web (desktop + mobile
responsive)"). The mockup provides no breakpoint or mobile layout, so there is nothing to specify
here and nothing to invent. Responsive behaviour for these regions is out of this story's scope —
the research assessment scored Compatibility 90 on exactly that basis.

## Tokens

`docs/design/tokens.md` holds the extracted palette, type scale and radii. The literal values quoted
above (`#0f1a2e` value text, `#7a828f` label, `#1f8a5b` sub) are taken from the decoded inline styles
— the mockups carry **inline styles only**, no CSS custom properties and no utility classes, so there
is no token *reference* in the markup to map back. Prefer the named token from `tokens.md` where one
matches; fall back to these literals where it does not.
