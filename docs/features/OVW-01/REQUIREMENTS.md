# Feature: OVW-01 — Org summary cards + adoption indicator

## Problem

A CIO has no organization-wide view of AI SDLC adoption. Every existing surface
(`/programs/[program_id]`) is scoped to one program; nothing answers "how much of the org is
actually using this?" in one glance. The root route (`/`) already redirects to `/overview`
(`ADOPTION_OVERVIEW_ROUTE`, referenced by PGD-01's back-to-board link), but that route 404s today
— nothing has ever implemented it.

## Outcome

A CIO landing on `/overview` sees, within the 3s budget (NFR-001), 5 org-wide summary cards and an
adoption-level indicator (`<count>/<total> — <adoption_percent>%`, progress bar, legend) sourced
from `GET /api/overview/summary`. Three states, no others: 200-with-data on a populated org, 200
all-zero on a fresh/never-ingested org, 403-no-body for every non-CIO persona. This also closes
PGD-01's carried-forward `back-to-board-route-placeholder` item — its "← Back to program board"
link stops 404ing.

## Constraints

- Design contract is the CIO Portfolio Dashboard mockup's `ORG SUMMARY` (`orgKpis`,
  `hint-placeholder-count="5"`) and `PROGRAM ADOPTION HEALTH` (`adoptionHeadline`/`adoptionPct`/
  `adoptionBarUsing`/`adoptionBarNot`/`adoptionLegend`) sections only. The same mockup's monthly
  token-cost bar chart, MAU-by-role, and program leaderboard sections belong to OVW-02/03/04.
- AC-6 is backend-only; no freshness timestamp renders anywhere on this page — settled 2026-09-09
  (story Decision log, research C-1: no mockup binding, PGD-01 precedent, `CLAUDE.md` § Design
  system). Not reopened here.
- Mockup is desktop-only (`docs/design/README.md`); no responsive breakpoint scale exists yet.
- AUTH-03's security review is open (`security: null`) though the `org_access()` implementation
  this story depends on is shipped and validated (Condition 1 below).
- `adoption_percent` must be nullable, never `0.0`, when `programs_total == 0` (BED-02 D-07,
  Condition 2 below).

## Solution sketch

Add `GET /api/overview/summary` to the existing `app/api/overview.py` router: gate on
`org_access()` (rbac-checks), read the `org_summary_rollup` singleton (falling back to an all-zero
envelope when the row is absent), compute the card values and adoption percentage via the existing
`format_number()`/`compute_adoption_percent()` helpers (api-conventions), and separately invoke
`FreshnessAccessor.get_last_successful_run()` purely for its backend error/observability behaviour
— nothing from that call is returned to the client. On the frontend, add a new `/overview`
Server-Component route that fetches through the `/api/proxy/*` pattern (AUTH-05) exactly like
`ProgramDetailView`, wraps a new `AdoptionOverview` client component in `PersonaDashboardShell`, and
renders the 5 summary cards plus the adoption progress bar/legend per the mockup.

## Addressing Research Conditions

- **Condition 1 (AUTH-03 upstream caveat)**: security review is open (`phase: security-review`,
  `security: null`) though `org_access()`'s implementation is complete and validated (`impl:
  complete`, `review: PASS`). Mitigation: proceed — this story calls the shipped `org_access()`
  as-is; document the caveat in the PR description so a later AUTH-03 security finding is triaged
  against AUTH-03, not re-litigated here.
- **Condition 2 (adoption % null handling)**: the route must return `adoption_percent = None`
  (never `0.0`) when `programs_total == 0` — the fresh-database path, easy to miss. Mitigation:
  **OVW-01-FR-1** pins `programs_using_ai.adoption_percent` as nullable in the response schema
  (both the missing-row/AC-2 case and the genuinely-zero-programs case); **OVW-01-FR-4** pins the
  corresponding UI render; a dedicated unit test asserting `adoption_percent is None` (not `0`) for
  both trigger cases is required coverage.

(Condition 3 — freshness timestamp placement — was resolved 2026-09-09 in the story's Decision log;
not reopened here.)

## Scope

- In:
  - `GET /api/overview/summary` route + response schema on `app/api/overview.py`.
  - All-zero fallback when `org_summary_rollup` is absent (AC-2).
  - `org_access` RBAC gate + inherited `rbac_check_org_access` logging (AC-3, AC-8).
  - Backend-only freshness read + error propagation (AC-6, AC-7) — nothing rendered.
  - `/overview` Next.js route (replaces today's 404) + `AdoptionOverview` client component: 5
    summary cards + adoption indicator (headline, bar, legend).
- Out:
  - Monthly token-cost bar chart, MAU by role, program leaderboard (OVW-02/03/04).
  - Any freshness/as-of timestamp UI (settled — AC-6 is backend-only).
  - Mobile/responsive layout (mockup is desktop-only; undesigned).
  - Program-level detail or drilldown (PGD-01..06).

## Functional requirements

FRs trace 1:1 to story ACs; see `docs/stories/OVW-01.md` for canonical wording.
New impl constraints introduced below:

**OVW-01-FR-1** — Response shape: pre-formatted card list + raw adoption fields *(extends AC-1,
AC-5 with: concrete wire shape)*

`GET /api/overview/summary` returns two top-level structures:
- `cards`: an ordered, exactly-5-entry list `{glyph, value, label, sub}`, one entry per AC-1 metric in
  AC-1's own enumeration order (`programs_using_ai`, `total_token_consumption`,
  `lines_of_code_generated`, `releases_using_harness`, `repos_with_harness_installed_over_total`) —
  mirrors `orgKpis`' `hint-placeholder-count="5"` and the `program-detail-api` `summary` card-list
  precedent (glyph/label fixed presentation constants owned by the producer).

  **Per-card `value` rules — corrected 2026-09-10 against the mockup's embedded sample-data script.**
  The previous text put the ratio treatment on card 5 (`repos_with_harness_installed_over_total`) and
  `format_number()` on card 1. The mockup's `const orgKpis = [...]` block has it the other way round:

  | # | Metric | `value` | `sub` |
  |---|---|---|---|
  | 1 | `programs_using_ai` | literal ratio `"{count} / {total}"`, **exempt** from `format_number()` | `"{pct}% adoption"` — see below |
  | 2 | `total_token_consumption` | `format_number()` | `null` |
  | 3 | `lines_of_code_generated` | `format_number()` | `null` |
  | 4 | `releases_using_harness` | `format_number()` | `null` |
  | 5 | `repos_with_harness_installed_over_total` | `format_number()` — a plain count, **not** a ratio | `null` |

  Card 5's metric id still reads `..._over_total` (it comes from AC-1's own enumeration and the id is
  not being renamed here), but the mockup renders it as a plain number. The mockup governs the
  rendering; the id is just a name.
  **`sub` — added 2026-09-09 after direct extraction of the mockup (orchestrator, Phase 2).** The
  `ORG SUMMARY` card template binds **four** fields, not three: `k.glyph`, `k.value`, `k.label` and
  `k.sub`. This FR originally specified only the first three, inherited from `program-detail-api`'s
  card shape — but that precedent is a genuine three-field one (the Program Detail mockup binds only
  `s.glyph`/`s.label`/`s.value`, and `ProgramSummaryCardData` in
  `apps/web/src/types/programDetail.ts:24-28` matches it exactly). The CIO Portfolio mockup binds one
  more, and per `CLAUDE.md` § Design system the mockup — not this prose — settles the response shape,
  so the field is part of the contract.

  Type: `sub: str | None`, **pre-formatted server-side** like `value` (same ADR-0007 reasoning —
  presentation is the producer's). It renders beneath `label` at 11px in `#1f8a5b` (green), so it is a
  positive/supplementary annotation, not a primary metric.

  The mockup guards it: `<sc-if value="{{ k.sub }}" hint-placeholder-val="x">`, so the element renders
  **only when `sub` is truthy**.

  **Corrected 2026-09-10.** This paragraph previously said the mockup "says nothing about what any
  given card's `sub` should say" and mandated `null` on all five. That was wrong, and wrong in a
  specific way worth recording: it was concluded from reading the *template bindings* only. The
  mockup's embedded `<script type="text/x-dc">` sample-data block **does** specify the content —
  the same block `ADR-0007` sourced Program Detail's glyph literals from, so there was an
  established precedent for looking there. What it actually says:

  - **Card 1**: `sub` = `Math.round((count / total) * 100) + "% adoption"` → e.g. `"70% adoption"`.
    Pre-formatted server-side like every other presentation value. When `programs_total == 0`,
    `adoption_percent` is `None` (`OVW-01-FR-4`) and there is no meaningful percentage, so `sub` is
    `null` and the `sc-if` omits the element — consistent with FR-4's `0/0` flat-bar empty state.
  - **Cards 2–5**: `sub: ''` in the sample data — falsy, so the `sc-if` omits the element. Ship
    `null` for these four.
- `programs_using_ai: {count: int, total: int, adoption_percent: float | null}` — kept separate
  from `cards` because it also drives the visually distinct adoption-indicator section (AC-4), not
  just its own summary card. `count`/`total` are raw ints (needed verbatim for AC-4's literal
  `<count>/<total>` headline and the legend's `h.count`). `adoption_percent` is `null`, not `0.0`,
  when `total == 0` (BED-02 D-07) — covers both the missing-row (AC-2) and genuinely-zero-programs
  cases.

Decision (logged): `adoption_percent` ships as a raw nullable number, not a pre-formatted percent
string. `compute_adoption_percent()` (api-conventions) is a computation, not a formatting function;
the mockup's unit-less `{{ adoptionPct }}` binding is satisfied by the route composing its own
display string at the schema layer (e.g. `f"{pct:.0f}%"`), the same way `program-detail-api`'s ratio
card is a route-composed string exempt from `format_number()`. This is consistent with the
server-side-pre-formatting precedent PGD-01/ADR-0007 already established for this codebase.

**OVW-01-FR-2** — No inline CSS in the wire response *(extends AC-4 with: presentation-vs-data
boundary)*

The mockup's `adoptionBarUsing`/`adoptionBarNot`/`adoptionLegend[].color` bindings are the canvas
template's own presentation mechanism (`docs/design/README.md`'s "templates also bind presentation"
caveat), not the wire contract. Per `program-detail-api`'s precedent (`avatarStyle`/`typeChip`
derived client-side via `programStyle.ts`, never shipped on the wire) and `api-conventions`'
derived-value layer note, the response ships only `programs_using_ai.{count, total,
adoption_percent}`; the frontend computes the two bar-segment widths (`adoption_percent`% /
`100 - adoption_percent`%) and the legend swatch colors from a small fixed client-side palette
(`docs/design/tokens.md`), not from a server-supplied CSS string.

**OVW-01-FR-3** — Freshness check is unconditioned by the `org_summary_rollup` lookup *(extends
AC-2, AC-6, AC-7 with: call ordering)*

AC-2 (missing `org_summary_rollup` → all-zero payload) and AC-7 (missing `system_metadata`
`ingestion` row → raise) are independent preconditions on two different tables, both reachable from
the same never-ingested database. The route calls `FreshnessAccessor.get_last_successful_run()`
exactly once per request, unconditioned by whether `org_summary_rollup` returned a row or the
all-zero fallback; a raised `HTTPException` from that call propagates as the request's response
(500), even on an otherwise-valid all-zero payload. Deliberate, not an oversight: AC-7 requires "a
clear error... rather than a silent or empty state," and in practice both rows are absent together
on a genuinely fresh database (the same ingest write path populates both), so silently swallowing
the freshness failure would mask the one signal distinguishing "never ingested" from "ingested, but
zero real adoption." Test coverage must include the fully-fresh case (both rows absent, expect 500)
in addition to the two isolated-row cases research already calls out.

**OVW-01-FR-4** — Null-adoption-percent render state *(extends AC-4 with: undesigned edge state)*

When `programs_using_ai.total == 0`, the adoption indicator cannot render a meaningful
`<count>/<total>` fraction or bar/legend proportions — the mockup has no such state
(`docs/design/README.md`). Decision (logged): render the headline literally as `0/0` with a flat,
single-color bar (no adopted/not-adopted split) and both legend entries showing `0`, rather than
inventing new mockup content (empty-state banner, hidden section) that `CLAUDE.md` § Design system
forbids. Same posture PGD-01/SHP-01 took for their own undesigned edge states.

## Non-functional requirements

- Performance: Dashboard render time ≤ 3s under normal load (NFR-001, story-sourced).
  `org_summary_rollup` is a single indexed-row read, no joins — research measured < 100ms; well
  within budget, no new numeric budget needed.
- Security: Per `.claude/rules/security-baseline.md`: applies to the new `GET
  /api/overview/summary` endpoint. Server-side-only RBAC — `org_access` (rbac-checks) gates the
  entire response, never UI-only hiding (NFR-005, FR-AUTH-05, story AC-3). AUTH-03's own security
  review being open is Condition 1 above — documented in the PR, not a merge blocker.
- Accessibility: Per `.claude/rules/accessibility-baseline.md`: applies to the two new `/overview`
  UI regions (org summary cards, adoption indicator). The progress bar's adopted/not-adopted split
  pairs color with the legend's count + label text (AC-4) — color is never the sole indicator.
- Observability: `rbac_check_org_access` structured JSON log fires on every request via
  `org_access()` (NFR-011, AC-8) — inherited from rbac-checks, no new logging code. The freshness
  accessor's own `logger.warning` on an absent row / timeout (freshness-api contract) fires
  automatically on the AC-7 path.

## Screen inventory

Scoped to the two in-scope regions of the CIO Portfolio Dashboard mockup
(`docs/design/mockups/CIO Portfolio Dashboard.html`, OVW epic). The monthly token-cost bar chart,
MAU-by-role, and program leaderboard sections in the same mockup belong to OVW-02/03/04 and are
excluded from this inventory.

| Screen | Route | Render | Primary purpose | States | Story ACs covered |
|---|---|---|---|---|---|
| Org summary cards | /overview | server (initial load, no client refetch) | 5 pre-formatted org-wide KPI cards, each `{glyph, value, label, sub}` with `sub` optional/`sc-if`-guarded (programs using AI, total token consumption, lines of code generated, releases using Harness, repos with Harness installed/total) — mockup `ORG SUMMARY` section, `orgKpis` (`hint-placeholder-count="5"`) | Populated / Loading / Empty (fresh DB — all-zero cards, AC2) / Error (403 non-CIO, AC3) | AC1, AC2, AC3, AC5 |
| Adoption level indicator | — (embedded below Org summary cards, same route) | server (initial load, no client refetch) | `<count>/<total> — <adoption_percent>% of the org` headline, 2-segment progress bar (adopted vs. not-yet-adopted), 2-entry legend — mockup `PROGRAM ADOPTION HEALTH` section | Populated / Empty (`programs_total=0` — null percent, flat bar per FR-4) / Error (403 non-CIO, AC3) | AC3, AC4 |

## Visual spec

See [DESIGN.md](./DESIGN.md) — the two in-scope mockup regions (`ORG SUMMARY`, `PROGRAM ADOPTION HEALTH`), their exact bindings, literal copy, states and form factors. Hand-authored during Phase 2: `ux-agent` is not installed in this repo, the same gap PGD-01 and SHP-01 recorded.

## Rollout plan

- **Strategy**: bang-bang — new route + new endpoint, no existing behaviour changed, additive only.
  Per `.claude/rules/reusability-baseline.md`, no config-switch is introduced to fork the call graph.
- **Feature flag**: none.
- **Backout plan**: remove the `/overview` route and the new `GET /api/overview/summary` handler
  from `overview.py`; `ADOPTION_OVERVIEW_ROUTE` reverts to 404ing, same as before this ships — no
  other shipped component depends on the route existing (PGD-01's link degrades gracefully, as it
  does today).
- **Success signal**: a CIO session's `GET /overview` returns 200 with rendered cards + indicator in
  < 3s (NFR-001); a non-CIO session gets 403 with no data body; both verified in staging before wider
  rollout.

## Documentation requirements

- **README updates**: `README.md` API table — add a `GET /api/overview/summary` row (request,
  response shape, 403/all-zero cases), matching the existing `/api/programs` / `/api/overview/
  program-detail/{program_id}` row format.
- **Runbook**: none.
- **API reference**: FastAPI's generated `/docs` (OpenAPI); the new response schema documents
  itself, no separate file.
- **Inline code comments**: `app/api/overview.py` — new route's docstring must note (a) no
  freshness timestamp is rendered anywhere on this page (guard against a future "helpful" addition;
  see Constraints and the story's Decision log), and (b) the freshness-check/`org_summary_rollup`
  independence from **OVW-01-FR-3**.
- **Examples / how-to**: none.

## Open questions

<!-- None open. Every PRD-level decision above (FR-1 percent-format, FR-2 no-inline-CSS, FR-3     -->
<!-- freshness/org_summary_rollup ordering, FR-4 null-adoption-percent render state) is sourced     -->
<!-- from an existing contract (api-conventions, freshness-api, program-detail-api precedent) or    -->
<!-- logged inline with reasoning, per the provenance rule. needs_clarification_count: 0.           -->
<!--                                                                                                 -->
<!-- Kept as a comment deliberately (matching docs/features/PGD-01/REQUIREMENTS.md,                 -->
<!-- docs/features/SHP-01/REQUIREMENTS.md): the phase-preconditions clarification gate treats ANY   -->
<!-- non-blank, non-comment line in this section as an unresolved open question.                    -->
<!--                                                                                                 -->
<!-- Decisions logged in docs/stories/OVW-01.md § Decision log (AC-6 backend-only, resolves         -->
<!-- research C-1).                                                                                 -->

## Approvals

| Role | Approver | Date | Verdict |
|---|---|---|---|
| Product Owner / BA | Pratik Pawar | 2026-09-09 | APPROVE |
| Designer | Pratik Pawar | 2026-09-09 | APPROVE — via [DESIGN.md](./DESIGN.md) (`design: complete`) |

Product Gate passed at `/arh-plan-requirements` Phase 4, verdict given by the approver in response to
the gate checklist. Every checklist item passed. Evidence at approval time:

- **2/2 live research conditions** addressed with concrete mitigations in § Addressing Research
  Conditions. The research report's third condition (freshness-timestamp placement) was resolved as
  clarification C-1 on 2026-09-09 and is referenced as settled, not reopened.
- **0 unresolved clarification markers, 0 open questions.**
- **No-placeholder check clean** — zero matches for TBD / TODO / "as appropriate".
- **Test-case coverage audit passes: `uncovered: []`** across 8 test cases (8 automatable), every
  `requirement_id` resolving to a real declared AC/FR/NFR id. Types: 1 contract, 5 integration,
  1 security, 1 performance. No `e2e`-typed case, because `test_e2e` is empty in
  `docs/config/project-commands.yaml` — an `e2e` case would be unrunnable today.
- **Design approved via `DESIGN.md`**, which specifies the two in-scope mockup regions
  (`ORG SUMMARY`, `PROGRAM ADOPTION HEALTH`), their exact bindings, literal copy, states and form
  factors. Note it was **hand-authored rather than generated**: `ux-agent` is not installed in this
  repo, the same gap PGD-01 and SHP-01 each recorded in their own `DESIGN.md`.
- **A response-shape correction was made during Phase 2 and is part of what was approved.** Direct
  extraction of `CIO Portfolio Dashboard.html` showed the `ORG SUMMARY` card template binds **four**
  fields — `k.glyph`, `k.value`, `k.label`, **`k.sub`** — while `OVW-01-FR-1` had specified only
  three, inherited from `program-detail-api`'s genuinely three-field shape. Per `CLAUDE.md` § Design
  system the mockup settles response shape, so `sub: str | None` is now in the contract. It is
  `<sc-if>`-guarded, so `null` for all five cards is a conformant render — the field's existence is a
  design fact, its content is not.
- Tracker subtasks: `pratikpawar009/Dashboard#264` (PRD), `#263` (research).

### Re-approval — 2026-09-10

| Role | Approver | Date | Verdict |
|---|---|---|---|
| Product Owner / BA | Pratik Pawar | 2026-09-10 | APPROVE (amendment) |

`OVW-01-FR-1` was amended after the original gate, during `/arh-plan-implementation` Phase 1. The
`impl-planning-agent` read one layer deeper into the mockup than Phase 2 had — into the embedded
`<script type="text/x-dc">` sample-data block, the same block `ADR-0007` sourced Program Detail's
glyph literals from — and found the approved FR-1 disagreed with the design contract in **three**
respects: card 1's `value` (ratio, not a bare count), card 1's `sub` (`"{pct}% adoption"`, not
null), and card 5's `value` (a plain count — the ratio treatment had been placed on the wrong
card). `docs/test-cases/OVW-01.json` TC-01 and TC-06 encoded the same errors.

All three were corrected in FR-1, the test manifest, `PLAN.md`, `tasks.json` T-03 and
`DECISIONS.md` D-02, rather than shipped and carried forward. Rationale: `CLAUDE.md` § Design
system makes the mockup authoritative on response shape, so a gate approval of a PRD that was
factually wrong *about the design contract* does not turn that error into a requirement — and
shipping it would have produced a page visibly differing from the design in three places. Caught
before any code existed, which is the cheapest possible point.

