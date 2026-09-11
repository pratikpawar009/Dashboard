# DESIGN: OVW-05 — CIO shell regions: signed-in identity block + org page-title header

**Provenance**: hand-authored 2026-09-11 during `/arh-plan-requirements` Phase 2. `ux-agent` is not
installed in this repo — `.claude/agents/` has no `ux-agent.md` — the same gap SHP-01, PGD-01 and
OVW-01 each hit and recorded in their own `DESIGN.md` files. This is the **fourth** occurrence; OVW-01
already reclassified it from surprise to standing condition and carried it forward for a decision on
whether to install the agent. Nothing new to add — this file was likewise written directly from the
design source instead of generated. It is a **pre-implementation spec**: the identity block and header
region exist in shipped code (SHP-01) but have never rendered, and neither new element below exists at
all. **The mockup, not this file, is the source of truth on any disagreement** — except for the two
regions explicitly marked recorded deviations, which the mockups do not contain.

**Design source**: `docs/design/mockups/CIO Portfolio Dashboard.html` (`docs/design/schema.json` → OVW
epic). A Claude Design canvas export — it must be decoded before the markup is readable;
`docs/design/README.md` § "These are bundler outputs" carries the procedure. Decoded document: 39,478
characters, identical decode to OVW-01's. Line references below are into that decode. `dashboards/` at
the repo root holds a byte-identical copy (SHP-01 § Provenance, OVW-01 § Design source); read the
`schema.json` path.

## Scope

Two screens, per `REQUIREMENTS.md` § Screen inventory. The decoded document's section comments are
`BRAND BAR`, `HEADER`, `CONTENT`, `ORG SUMMARY`, `ORG MONTHLY TOKEN COST BAR CHART`,
`MONTHLY ACTIVE USERS BY ROLE`, `PROGRAM ADOPTION HEALTH`, `PROGRAM LEADERBOARD`.

| Screen | Region | Component | Mockup anchor |
|---|---|---|---|
| `/overview` | Signed-in identity block | `PersonaDashboardShell.tsx` (inline, per SHP-01 D-01) | `<!-- BRAND BAR -->` L385–391 |
| `/overview` | Org page-title header | `PersonaDashboardShell.tsx`, new `pageTitle` variant | `<!-- HEADER -->` L394–403 |
| `/overview` | Sign-out control | same identity block | **none — recorded deviation A** |
| `/login` | Branded sign-in page | `apps/web/src/app/login/page.tsx` (new) | **none — recorded deviation B** |

Explicitly **not** in scope though the same mockup renders them: `ORG SUMMARY` and
`PROGRAM ADOPTION HEALTH` (OVW-01, shipped), the token-cost bar chart / MAU-by-role / leaderboard
(OVW-02/03/04). The brand bar's **left** half (logo tile + product name + tagline) is shipped
unchanged by SHP-01 and is not re-specified here — it is only *reused verbatim* by deviation B.

---

## Screen 1 — `/overview`

### Region 1 — `BRAND BAR`, right half (signed-in identity block)

Already built by SHP-01 (`PersonaDashboardShell.tsx` + `PersonaDashboardShell.module.css`) and
permanently suppressed today, because `AdoptionOverview` omits `persona` and the shell's
`isLoading = persona === undefined` gate therefore never opens. **This story changes no geometry in
this region** — it supplies the props that let the shipped markup render, plus deviation A.

#### Literal copy — what ships vs what the mockup says

| Element | Mockup literal (L387–390) | What ships |
|---|---|---|
| Name | `Elena Vasquez` | `GET /api/me`'s `name`, never the sample. `docs/design/README.md` § Recorded divergences: the five sample names "are never shipped, not even as fallback copy" |
| Job title | `Chief Information Officer` | **verbatim** — `PERSONA_DISPLAY.cio.jobTitle` (AC-3) |
| Avatar initials | `EV` | `deriveInitials(name)`, shipped |

`Chief Information Officer` is the one job-title literal this story ships unchanged. The Architect and
Developer mockups' `Principal Architect` / `Senior Developer` are the two that do **not** — they assert
seniority the system holds nowhere, and `docs/design/README.md` § Recorded divergences already logs the
weaker-true-string rule with OVW-05 named as the story that lands it. `Chief Information Officer` is not
in that category: it is the plain role name for the `cio` persona, identical to what the rule would
produce anyway.

#### Bindings

| Binding | Source | Style (shipped, byte-exact from L386–390) |
|---|---|---|
| Name | `signedInUser.name` ← `GET /api/me` | `13px` / `600` / `line-height:1.2`, right-aligned |
| Job title | `PERSONA_DISPLAY[persona].jobTitle` — **composed frontend-side, never on the wire** (`MeResponse` is `extra="forbid"`, AUTH-07) | `11px` / `500` / `#8a93a1` |
| Avatar | `deriveInitials(name)` on `formatPersonaTag(persona).color` | `34×34` · `border-radius:50%` · `13px` / `700` · `#fff` on `#0f1a2e` for `cio` (AC-2/AC-6) |
| Row | — | `display:flex; align-items:center; gap:10px` |

`#0f1a2e` reaches the avatar as `formatPersonaTag('cio').color`, the same value the org header's pill
uses for its text — so SHP-01 D-02's "the tag and the avatar can never disagree on a persona's colour"
holds structurally for `cio` too, not by coincidence.

#### States

| State | Rendering |
|---|---|
| Populated (`name` non-null) | name + job title + initials avatar, as above |
| Empty (`name: null`, AC-7) | shipped D-05 neutral fallback — `34×34` circle, `var(--neutral-unresolved-bg)`, no initials, `aria-hidden="true"`. Never `Elena Vasquez`, never a blank field |
| Loading (`persona === undefined`, AC-10/AC-14) | whole block omitted, brand-bar left half only. No skeleton — FR-5 flash prevention, unchanged |
| Persona unresolvable, name known | shipped `.avatarUnknownPersona` (FLAGS.md AF-03) — initials on the shared neutral pair |

### Region 2 — `HEADER`, org variant (new)

`<header>` L395: `padding:20px 34px` · `display:flex; align-items:center; gap:20px` ·
`border-bottom:1px solid #e9ebef` · `background:#ffffffcc` · `backdrop-filter:blur(8px)` ·
`position:sticky; top:0; z-index:5`. Single child `<div style="flex:1">` (L396).

| Element | Line | Literal / binding | Style |
|---|---|---|---|
| Title row | L397 | — | `display:flex; align-items:center; gap:10px` |
| Page title | L398 | `Adoption Overview` — the `pageTitle` prop, passed by `AdoptionOverview` (AC-9), not a shell constant | `19px` / `700` / `letter-spacing:-.3px`, inherits body `#151a22` |
| Persona pill | L399 | `formatPersonaTag(persona).tag` → `CIO / CXO` | `11px` / `700` · `color:#0f1a2e` · `background:#e6e9ef` · `padding:3px 9px` · `border-radius:20px` |
| Subtitle | L401 | `formatPersonaTag(persona).subtitle` → `Organization-wide AI-in-SDLC adoption, spend & impact` | `12.5px` / `500` / `#7a828f` · `margin-top:2px` |

The pill's geometry is **identical** to `PersonaHeader.module.css`'s shipped `.pill` rule — same four
declarations, no new pill. Its colour pair arrives via `style` as `{color, background}`, matching
SHP-01 D-06's "only the data-driven pair crosses as a `CSSProperties` prop".

**`PersonaHeader` itself is not reusable here, and that is why AC-8 asks for a second composition.**
`PersonaHeader` lays the pill and the subtitle out on *one* flex line (`gap:8px`, `margin-bottom:12px`)
under a `program`-bearing header; the org variant puts title+pill on line one and the subtitle beneath.
Same two values, different composition. Reuse `formatPersonaTag()`, not `PersonaHeader`.

**Selection is by prop presence only** (AC-8): `pageTitle !== undefined && program === undefined &&
!isLoading`. Mutually exclusive with the shipped `program !== undefined` variant. No `persona === 'cio'`
— or any persona-literal — conditional may appear in `PersonaDashboardShell.tsx`; the file has never had
one (its own docstring states this as research condition C-7) and this story must not be the first.

#### States

| State | Rendering |
|---|---|
| Populated | title + pill + subtitle as above |
| Loading (`persona === undefined`) | header omitted entirely — no title, no pill, no skeleton (AC-10) |
| Persona unresolvable | pill slot degrades to the shared neutral `Persona unavailable` badge (`--neutral-unresolved-*`) plus the visually-hidden `aria-live="assertive"` announcement, exactly as `PersonaHeader` already does — the title still renders. Per `REQUIREMENTS.md` § Screen inventory; no new error treatment is invented. Mechanically this means the org variant needs the same `PersonaTagError` catch `PersonaHeader` has — extract-vs-duplicate is an implementation call, listed under § Open design items |
| `program` also defined | not a state — a caller error. The two header variants are exclusive by construction |

**Geometry divergence from the shipped `.headerRegion` rule.** The CIO mockup's header pads
`20px 34px`; the four persona mockups pad `18px 34px 20px`, which is what
`PersonaDashboardShell.module.css` `.headerRegion` ships. A 2px top-padding difference. Per `CLAUDE.md`
the mockup is the contract, so the org variant takes `padding:20px 34px` — a modifier class, not an edit
to the existing rule, which the program variant still needs unchanged. Flagged for the gate rather than
decided silently, since "reuse `.headerRegion` as-is and absorb 2px" is a defensible alternative.

---

## Recorded deviation A — sign-out control (ACs 12–15)

**Not in any mockup.** Verified 2026-09-11 by decoding all six exports and searching each: zero matches
for `sign out` / `signout` / `log out` / `logout` in any of them. (The three `SSO` substring hits are
inside a program's `scope` prose — "Enterprise-wide SSO and zero-trust access mo…" — not an affordance.)
`CLAUDE.md` § Design system forbids inventing UI the mockups do not show and requires the gap be raised
instead. **It was raised and the user decided**: see `docs/stories/OVW-05.md` § Decision log, entry dated
2026-09-11 ("Sign-out control added to the signed-in identity block — deliberate deviation from the
mockups, per explicit user direction"). Not re-litigated here. No UI beyond what that entry describes.

**Built from existing brand-bar tokens only. No new visual language** (AC-15).

| Property | Value | Where it comes from |
|---|---|---|
| Placement | last child of the shipped `.identity` flex row, **after** the avatar | append-only; the mockup's own name→title→avatar order is untouched |
| Render condition | `!isLoading` — a sibling of the `signedInUser ? … : …` ternary, **outside** it | AC-12 says the control renders whenever the block does, and the block renders in *both* the populated and the neutral-fallback branch. Placing it inside either branch would drop it in the other. AC-14 falls out for free: the block's existing all-or-nothing `isLoading` gate already covers it |
| Gap | `10px` | the row's shipped gap |
| Label | visible text `Sign out` | — |
| Type scale | `12px` / `600` | `size-secondary`, `docs/design/tokens.md` § Typography |
| Colour, rest | `#5b6472` (`text-700`) | **5.98:1 on `#fff`.** Not `#8a93a1`/`#7a828f`, the two greys the adjacent job title and subtitle use — both fail AA on white (3.10 / 3.88, SHP-01 § Design QA). A new interactive control must not inherit a known-failing pair |
| Colour, hover/focus | `#2a6fdb` (`primary`) | 4.78:1 on `#fff`. Mirrors PGD-01's back-to-board link convention (`#7a828f` → `#2a6fdb`), starting from the accessible grey |
| Focus ring | `outline:2px solid #2a6fdb; outline-offset:2px` | 4.78:1 vs `#fff` surround, clearing WCAG 1.4.11's 3:1 non-text bar |

**Markup — a zero-JS form, not an anchor and not a client button:**

```html
<form action="/logout" method="get">
  <button type="submit" aria-label="Sign out">Sign out</button>
</form>
```

Why this shape: AC-13 requires navigation to the existing `GET /logout` Route Handler and forbids any
new logout logic, while the a11y bar calls for a semantic `<button>` with `aria-label="Sign out"` and a
visible focus ring. A plain `<button onClick>` would force `"use client"` on `PersonaDashboardShell`,
which is a Server Component today and whose whole contract is "props only, no data fetching". A GET form
submit navigates natively, keeps the shell server-rendered, and gives a real `<button>` with native
keyboard activation (Enter and Space) and native focus. The plain `<a href="/logout">` alternative is
equally accessible but is not a `<button>`; recorded as the runner-up, not the choice. Note the submit
produces `/logout?` (trailing `?`, no params — the form has no named inputs); the Route Handler matches
on path and is unaffected.

`aria-label="Sign out"` is byte-exact and **must match the visible label** (WCAG 2.5.3 Label in Name).
If the control is ever reduced to a glyph, the `aria-label` is what carries the accessible name.

---

## Recorded deviation B — branded `/login` sign-in page (ACs 16–19)

**Not in any mockup** — same verification as deviation A; none of the six exports contains a sign-in
screen. Same authority: `docs/stories/OVW-05.md` § Decision log, 2026-09-11 ("Branded sign-in page takes
`/login`; the OAuth relay handler moves to `/login/start`" and "Branded sign-in page folded into THIS
story (moved from `AUTH-05`), per user direction"). Not re-litigated here.

**Built from existing brand-bar and card tokens only** (AC-19). Every value below traces to a shipped
rule or a `docs/design/tokens.md` entry; nothing is a new visual idea.

`apps/web/src/app/login/page.tsx`, a Server Component. Composition, top to bottom:

| Element | Spec | Source |
|---|---|---|
| Page ground | `#f5f6f8`, `min-height:100vh`, centred column (`display:flex; align-items:center; justify-content:center`) | `#f5f6f8` is the decoded mockups' own `body{background:…}` (L367) |
| Card | `background:#fff` · `border:1px solid #e6e9ef` · `border-radius:16px` · `box-shadow:0 1px 2px rgba(15,26,46,.04)` | `docs/design/tokens.md` § Card recipe, verbatim |
| Logo tile | `32×32` · `border-radius:9px` · `background:#2a6fdb`; inner `13×13`, `border:2.4px solid #fff`, `border-radius:4px`, `transform:rotate(45deg)` | brand bar L378–379, verbatim |
| Product name | `AgentRise Harness` — `15px` / `800` / `letter-spacing:-.3px` | brand bar L382, verbatim |
| Tagline | `AI SDLC Governance` — `10.5px` / `600` / `#8a93a1` / `letter-spacing:.2px` / `margin-top:1px` | brand bar L383, verbatim |
| SSO action | filled `#2a6fdb`, `#fff` text, `13.5px` / `700`, `padding:9px 14px`, `border-radius:10px`, full card width | geometry from the only button the design source contains (Program Detail's switcher trigger, PGD-01 § Region 3); fill+text pair from the logo tile's brand blue and the avatar's white-on-brand precedent. **4.78:1** |
| SSO focus ring | `outline:2px solid #2a6fdb; outline-offset:2px` | same rule as deviation A — the offset puts the ring on the white card, not on the button's own blue |

**The brand identity is a centred stack, not the app's brand bar strip.** Rendering
`PersonaDashboardShell` here was considered and rejected: a pre-auth page has no `persona`, so the shell
would mount straight into its `isLoading` branch and deliberately suppress everything but the logo and
tagline — the right pixels for the wrong reason, and a live coupling between the sign-in screen and the
identity gate. AC-16 asks for "the same brand-bar *identity*" — the three elements — which the table
above reproduces byte-exactly without the coupling.

**Markup** — same zero-JS form as deviation A, one pattern in both places:

```html
<form action="/login/start" method="get">
  <button type="submit">Sign in with SSO</button>
</form>
```

No `aria-label`: the visible text `Sign in with SSO` **is** the accessible name, which is preferable to
an override (AC-17 accepts "or equivalent"). Activating it enters AUTH-05's shipped authorization-code
flow unmodified — `/login/start` is today's `login/route.ts` relocated one segment with its body
byte-identical (OVW-05-FR-2).

**Authenticated visitor (AC-18): nothing renders.** `readSession()` runs server-side before any markup;
a valid session `redirect()`s to `ADOPTION_OVERVIEW_ROUTE`. There is no visual state for this path — no
spinner, no "redirecting…" copy. Do not add one.

| State | Rendering |
|---|---|
| Unauthenticated | the card above, single SSO action |
| Authenticated | server `redirect()`, no paint |
| `/login/start` relay failure | the relay's existing plain-text `502` "Sign-in is unavailable." — shipped behaviour, not restyled by this story |

---

## Design QA — contrast audit (new and newly-reachable pairs)

SHP-01 § Design QA audited the shell's 22 pairs and found 13 below their bar, every failing value the
mockups' own. This audit covers only what OVW-05 adds or makes reachable for the first time. WCAG 2.2
relative-luminance formula; 4.5:1 normal text, 3:1 large text (≥18.66px bold) and non-text.

| Element | fg | bg | Ratio | Bar | |
|---|---|---|---|---|---|
| CIO identity avatar initials | `#ffffff` | `#0f1a2e` | 17.39 | 4.5 | PASS |
| CIO persona pill (org header) | `#0f1a2e` | `#e6e9ef` | 14.30 | 4.5 | PASS |
| Org header page title (19px/700) | `#151a22` | `#ffffff` | 17.46 | 3.0 | PASS |
| **Sign-out control, rest** | `#5b6472` | `#ffffff` | 5.98 | 4.5 | PASS |
| **Sign-out control, hover/focus** | `#2a6fdb` | `#ffffff` | 4.78 | 4.5 | PASS |
| **Sign-out focus ring** | `#2a6fdb` | `#ffffff` | 4.78 | 3.0 | PASS |
| **SSO button label** | `#ffffff` | `#2a6fdb` | 4.78 | 4.5 | PASS |
| **SSO focus ring** | `#2a6fdb` | `#ffffff` | 4.78 | 3.0 | PASS |
| Sign-in page product name | `#151a22` | `#ffffff` | 17.46 | 4.5 | PASS |
| Org header subtitle | `#7a828f` | `#ffffff` | **3.88** | 4.5 | **FAIL — inherited** |
| Identity job title | `#8a93a1` | `#ffffff` | **3.10** | 4.5 | **FAIL — inherited** |
| Sign-in page tagline | `#8a93a1` | `#ffffff` | **3.10** | 4.5 | **FAIL — inherited** |

**Every pair this story introduces passes.** The three failures are the two global greys SHP-01 already
evidenced and carried forward (`#7a828f`, `#8a93a1`, `docs/design/tokens.md`); OVW-05 reproduces them
byte-exactly rather than diverging unilaterally from the design source. One thing does change: the
tagline's 3.10:1 now appears on `/login`, an **unauthenticated** surface — the first time an inherited
contrast failure is visible before sign-in. Added to § Open design items; not fixed here, because
darkening a global grey has blast radius across all six dashboards and is a design decision, not an
implement-phase edit.

`#2a6fdb` clears 4.5:1 on `#ffffff` (4.78) but **not** on the `#f5f6f8` page ground (4.42). Both uses
above sit on white — the brand bar and the card. Do not move either onto the page ground.

## Keyboard and assistive tech

- Both new controls are real `<button type="submit">` elements: native tab order, native Enter/Space
  activation, native focus. No `tabindex`, no key handlers, no `role` overrides.
- Tab order on `/overview` follows DOM order, and the sign-out control is the identity row's last child
  — so it is the last stop in the brand bar, reached after the page's chrome, not before the content.
- `/login` has exactly one focusable element.
- The neutral avatar fallback stays `aria-hidden="true"` (AC-7). Adding the sign-out control to the same
  row does **not** make the row aria-hidden — only the decorative circle is.
- The org header's unresolvable-persona path reuses the shipped visually-hidden `aria-live="assertive"`
  announcement ("Unable to load your dashboard view."), clip-rect not `display:none`.

**The repo has no `:focus` or `:focus-visible` rule anywhere in `apps/web/src`** (verified 2026-09-11),
and the mockups specify no interactive states at all — no hover, no focus, no disabled. The outline
values above are therefore the WCAG/browser-default fallback, stated plainly as such per
`.claude/rules/project-standards.md`, not this team's existing convention. They are the first focus rule
in the codebase; a later house convention supersedes them.

## Form factors

**Desktop-only**, for `/overview` — `docs/design/README.md` and `docs/design/tokens.md` § Responsive
both record all six mockups as a fixed `1360px` column with no breakpoints, against `CLAUDE.md`'s
"Web (desktop + mobile responsive)" target. Nothing to specify and nothing to invent; both regions
inherit SHP-01's position exactly.

`/login` has no mockup at all, so there is no desktop composition to inherit either. A centred
single-column card with a bounded width is intrinsically fluid and needs no breakpoint — the one screen
in this story that is not desktop-only by inheritance.

## Tokens

`docs/design/tokens.md` holds the extracted palette, type scale and radii. Literal values above are
byte-exact from the decoded inline styles; the mockups carry **inline styles only**, no custom
properties and no utility classes, so there is no token *reference* in the markup to map back. Prefer
the named token where one matches (`primary` `#2a6fdb`, `text-700` `#5b6472`, `border-200` `#e6e9ef`,
`ink` `#0f1a2e`, `size-secondary` `12px`, `card` `16px`), fall back to the literal where it does not
(`#151a22` body ink and `#f5f6f8` page ground are both in the mockups but absent from `tokens.md`).
Static values become literal rules in a CSS Module per SHP-01 D-06; only `formatPersonaTag()`'s
`{color, background}` pair crosses as a `style` prop.

## Open design items for the gate

1. **Org header top padding** — mockup `20px 34px` vs shipped `.headerRegion` `18px 34px 20px`. Spec'd
   as a modifier taking the mockup's value; "absorb the 2px and reuse the shipped rule" is the
   alternative.
2. **Sign-in card width** — the one value in this file no source settles. The design source has no
   sign-in screen and `tokens.md` has no form/card width token (`content-max-width: 1360px` is a page
   column, not a card). Needs a number at implementation; flagged rather than invented.
3. **`PersonaTagError` catch in the org header variant** — share `PersonaHeader`'s existing catch or
   duplicate it. A structural call (`.claude/rules/reusability-baseline.md`), not a visual one.
4. **Inherited grey contrast now reaches a pre-auth surface** — `#8a93a1`'s 3.10:1 tagline ships on
   `/login`. Same carried SHP-01 defect, wider audience.

None blocks the PRD. Items 1–3 need a decision before the components are built; item 4 is a standing
carry-forward.
