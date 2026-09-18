# Feature: OVW-04 — Program board

## Problem

A CIO scanning org-wide AI SDLC adoption (OVW-01's summary cards) has no way to see which
*individual* programs are driving that adoption, or to jump into one. `/overview` today stops at
aggregate cards and an adoption bar — there is no ranked list of programs, so a CIO who wants to
know "who's adopting the most, who isn't, and where do I click to look closer" has no surface for
it.

## Outcome

A CIO on `/overview` sees a ranked "program leaderboard" — every program using Harness, ordered by
token consumption descending — each card showing identity (icon, name, type tag, description), a
monthly token sparkline with a month-over-month change indicator, four totals (tokens, releases,
features, active contributors), a "repos with Harness installed" ratio + progress bar, and a
navigation affordance that opens that program's Program Detail page. A non-CIO session gets `403`
with no data body. An org with no programs yet gets `200` with an empty list, not an error.

## Constraints

- Design contract is the CIO Portfolio Dashboard mockup's `PROGRAM LEADERBOARD` section only
  (`docs/design/mockups/CIO Portfolio Dashboard.html`, `docs/design/README.md`). The same mockup's
  `ORG SUMMARY`, monthly token-cost bars, MAU-by-role, and adoption-health sections belong to
  OVW-01/02/03 and are out of scope here.
- Mockup is desktop-only (`docs/design/README.md`); no responsive breakpoint scale exists yet.
- Values arrive pre-formatted server-side (`docs/design/README.md` § "Values arrive pre-formatted")
  — every wire field the mockup binds unit-less (`{{ p.value }}`) is a pre-formatted string, mirroring
  `program-detail-api`'s precedent, except where an established sibling precedent (token-trend,
  session-time-series) deliberately ships raw ints for magnitude fields the frontend formats itself.
- Presentation-vs-data boundary: per `docs/design/README.md` § "templates also bind presentation" and
  OVW-01-FR-2's precedent, styling fields (`cardStyle`, `avatarStyle`, `typeChip`, `momColor`,
  `momBg`, `repoBarStyle`) are derived client-side from `docs/design/tokens.md` and the program's
  `type`/data, never shipped as CSS strings on the wire.
- AUTH-03's security review is open (`security: null`) though the `org_access()` implementation this
  story reuses is shipped and validated (Condition mitigation below, same caveat OVW-01 recorded).

## Solution sketch

Add `GET /api/overview/program-board` to the existing `app/api/overview.py` router: gate on
`org_access()` (cio-only, same as OVW-01's `/api/overview/summary`), read `program_summary` rows
ordered by `tokens DESC` with offset/limit pagination (default 20, clamp 100), build one board card
per row via a new `fetch_program_board()` service function — computing the month-over-month change
indicator from `monthly_token_sparkline`, validating the JSONB shape with a safe empty-array
fallback — and format every numeric total via `format_number()`. On the frontend, extend the
`/overview` page (OVW-01) with a `ProgramLeaderboard` client component rendering `ProgramCard`
children; selecting a card or its navigation affordance routes to `/programs/{program_id}`
(AUTH-04's route convention), matching the mockup's `href` link pattern.

## Addressing Research Conditions

- **C-1 (index verification for `tokens DESC` ordering)**: `program_summary.tokens` must be indexed
  before implementation, or the migration adds the index. Mitigation: **OVW-04-FR-2** requires the
  route's query to use `ORDER BY tokens DESC` against an indexed column; `/arh-plan-implementation`
  task list must include an explicit index-verification task against BED-01's `program_summary`
  migration before any handler code is written — a missing index blocks merge, not just a later
  perf finding.
- **C-2 (JSONB sparkline validation)**: `monthly_token_sparkline` must be validated before rendering
  a sparkline or MoM figure. Mitigation: **OVW-04-FR-3** pins the exact fallback contract — null,
  missing, or malformed JSONB (not a list of `{month, tokens}` pairs) yields an empty sparkline
  array and a neutral change indicator, never a 500. Test coverage requires a fixture with malformed
  JSONB asserting the fallback, not just the happy path.
- **C-3 (month-over-month edge case)**: programs with fewer than 2 months of token history cannot
  compute a MoM delta. Mitigation: **OVW-04-FR-3** also pins the neutral-state contract for
  0-point and 1-point sparklines (see below); test fixtures must cover zero-month, one-month, and
  multi-month (≥2) scenarios per the research condition's own wording.

## Scope

- In:
  - `GET /api/overview/program-board` route + response schema on `app/api/overview.py`.
  - `fetch_program_board()` service: query `program_summary` ordered by `tokens DESC`, paginated
    (default 20, clamp 100), builds per-program cards with computed MoM indicator.
  - `org_access` RBAC gate (cio-only) + `rbac_check_org_access` logging (inherited from OVW-01).
  - Empty-org `200` with `items: []` (AC-5).
  - JSONB sparkline validation + neutral-state fallback (research C-2/C-3).
  - Frontend `ProgramLeaderboard` + `ProgramCard` components on the existing `/overview` route
    (OVW-01), with navigation to `/programs/{program_id}` (AUTH-04 route convention).
- Out:
  - Org summary cards, adoption indicator (OVW-01 — already shipped).
  - Monthly token-cost bar chart, MAU-by-role sections (OVW-02/OVW-03).
  - Program Detail page content itself (PGD-01..07 — this story only navigates there).
  - Mobile/responsive layout (mockup is desktop-only; undesigned).
  - Filtering, sorting-by-other-columns, or search on the board (not in AC-1..6; deferred to a
    future story if requested).

## Functional requirements

FRs trace 1:1 to story ACs; see `docs/stories/OVW-04.md` for canonical wording.
New impl constraints introduced below:

**OVW-04-FR-1** — Response shape: paginated card list, mixed pre-formatted/raw fields *(extends
AC-1, AC-4, AC-6 with: concrete wire shape)*

`GET /api/overview/program-board` returns:

```
{
  "items": [
    {
      "program_id": str,
      "name": str,
      "type": str,               // program_summary.type, e.g. "Greenfield feature development"
      "icon": str,                // avatar abbreviation source (e.g. "G") — style derived client-side
      "description": str,         // mockup's p.scope
      "href": str,                // "/programs/{program_id}" (AUTH-04 route convention)
      "sparkline": {
        "points": [{"month": str, "tokens": int}],   // raw ints — frontend renders the mini-chart
        "mom_change_percent": float | null,           // null when < 2 points (FR-3)
        "mom_direction": "up" | "down" | "flat" | null
      },
      "metrics": [                 // ordered 4-entry array, ADR-0007 shape (D-01)
        {"glyph": str, "label": str, "value": str}   // value = format_number()
      ],
      "repos_with_harness_installed": int,   // raw int
      "repos_total": int                     // raw int — frontend composes "5/6" + bar width
    }
  ],
  "page": int,
  "page_size": int,
  "total": int
}
```

Rationale for the raw-vs-formatted split: `metrics[].value` carries
the mockup's four metric-box values (`{{ m.value }}`, unit-less bindings) — pre-formatted per
`docs/design/README.md`, mirroring `program-detail-api`'s `summary` card precedent. `sparkline.points`
and `repos_with_harness_installed`/`repos_total` ship as raw ints, matching the token-trend and
releases-row precedent (README.md § API) where the frontend owns ratio/bar-width composition and
chart rendering rather than receiving a pre-rendered SVG or string — the mockup's `p.repoLabel`
("5/6") and `p.repoBarStyle` (fill width) are both cheaply derivable client-side from two ints, and
shipping a server-composed ratio string here (unlike OVW-01's card-1 ratio, which is a headline
metric) would duplicate the same derivation the frontend already does for `repoBarStyle`.
`metrics` is an ordered 4-entry array of `{glyph, label, value}` in the fixed order the mockup
binds (`⬡ Total tokens`, `⤴ Releases via Harness`, `✦ Features via Harness`, `⚇ Active
contributors`). `glyph` and `label` are server-owned presentation constants per ADR-0007, matching
OVW-01's `orgKpis` and PGD-01's `summary` on the same page; only `value` varies per program. Order
is the contract — the mockup's `sc-for` binds `{icon, label, value}` per entry, so the labels are
template-bound, not hardcoded markup, and a bare-value array would put the label copy in two places.
`icon` (the avatar abbreviation, e.g. "G") stays on the wire: it is the avatar *letter*, which
`apps/web/src/lib/programStyle.ts` does NOT derive — that helper maps `type` to *colors* only — and
PGD-01 already ships the same field (`services/api/app/schemas/program_detail.py:12`).
`items` is ordered `tokens DESC` (AC-1); pagination fields mirror the `program_releases` precedent
(`page`/`page_size`/`total`, PGD-03) rather than `offset`/`limit` echo, since this is a full item
list, not a windowed sub-resource.

**OVW-04-FR-2** — Pagination defaults and ordering *(extends AC-1, AC-6 with: concrete params)*

`?page` (default `1`, `ge=1`) and `?page_size` (default `20`, clamped to max `100` — never
422-rejected above the max, per the `api-conventions` clamp precedent, story Decision log). Query
uses `ORDER BY program_summary.tokens DESC` against an index on `tokens` (research C-1) —
verified or added before implementation (see § Addressing Research Conditions).

**OVW-04-FR-3** — Sparkline validation and MoM neutral-state fallback *(extends AC-1 with: data
integrity + edge-case contract, research C-2/C-3)*

`program_summary.monthly_token_sparkline` (JSONB) is validated before use: null, missing, or a
value that is not a list of `{month: str, tokens: int}` objects yields `sparkline.points: []`.
MoM computation:

| `points` length | `mom_change_percent` | `mom_direction` |
|---|---|---|
| 0 | `null` | `null` |
| 1 | `null` | `null` |
| ≥2 | `(points[-1].tokens - points[-2].tokens) / points[-2].tokens * 100`, rounded to 1 decimal; `null` if `points[-2].tokens == 0` | `"up"` / `"down"` / `"flat"` (±0.05% threshold) |

A neutral (`null`/`null`) result renders without an arrow or color per FR-4 (frontend); it is never
an error and never blocks the rest of the card from rendering.

**OVW-04-FR-4** — Non-CIO rejection and empty-org response *(extends AC-2, AC-5 with: status code
provenance)*

Non-CIO session: `HTTP 403`, no data body, `rbac_check_org_access` logged with outcome `denied` —
same `org_access()` gate and status code OVW-01 already established for `/api/overview/summary`.
Empty org (`program_summary` has zero rows): `HTTP 200` with `{"items": [], "page": 1, "page_size":
20, "total": 0}` — never a 404 or 500, consistent with the `overview-summary-api` all-zero
precedent (story AC-5, Decision log).

## Non-functional requirements

- Performance: endpoint budgeted at p95 < 300ms for a default `page_size=20` request — assumption
  carried from the story's Decision log (single indexed-column-ordered read against
  `program_summary`, consistent with sibling `program-detail-api` routes' measured latencies).
  Overall page contribution stays within the existing NFR-001 (≤3s) dashboard-render budget
  (OVW-01, sourced) — this endpoint is an additional fetch on the same page, not a new budget.
- Security: Per `.claude/rules/security-baseline.md`: applies to the new `GET
  /api/overview/program-board` endpoint. `org_access` (cio-only) enforced server-side, never
  UI-only hiding — same gate and caveat as OVW-01 (AUTH-03 security review open, documented in the
  PR, not a merge blocker).
- Accessibility: Per `.claude/rules/accessibility-baseline.md`: applies to the new
  `ProgramLeaderboard`/`ProgramCard` UI. Each sparkline's MoM change indicator pairs an icon/label
  with color — never color alone — matching OVW-01's adoption-bar precedent.
- Observability: `rbac_check_org_access` logged on every request (inherited from `org_access()`,
  same event as OVW-01); `program_drilldown` event logged when a program card's navigation
  affordance is selected (story NFR, sourced) — reuses the event name already defined by the
  `program-detail-api` drilldown logging convention (README.md § API,
  `/session-time-series` row).

## Screen inventory

Scoped to the one in-scope region of the CIO Portfolio Dashboard mockup
(`docs/design/mockups/CIO Portfolio Dashboard.html`, OVW epic). `ORG SUMMARY`, monthly token-cost
bars, MAU-by-role, and `PROGRAM ADOPTION HEALTH` belong to OVW-01/02/03 and are excluded.

| Screen | Route | Render | Primary purpose | States | Story ACs covered |
|---|---|---|---|---|---|
| Program leaderboard | /overview | server (initial load, no client refetch) | Ranked list of program cards (icon/name/type/description, token sparkline + MoM indicator, 4 metric totals, repos-installed ratio + bar, navigation affordance) — mockup `PROGRAM LEADERBOARD` section | Populated / Loading / Empty (no programs, AC-5) / Error (403 non-CIO, AC-2) | AC-1, AC-2, AC-4, AC-5, AC-6 |
| Program card navigation | — (embedded card affordance, same route) | client | Selecting a card or its arrow navigates to that program's Program Detail page | Populated only (no distinct empty/error state — action, not content) | AC-3 |

## Visual spec

See [DESIGN.md](./DESIGN.md) — the in-scope mockup region (`PROGRAM LEADERBOARD`), its exact bindings, literal copy, card anatomy, states and form factors. Hand-authored during Phase 2: `ux-agent` is not installed in this repo, the same gap SHP-01, PGD-01, OVW-01 and OVW-05 recorded.

## Rollout plan

- **Strategy**: bang-bang — new route handler, new UI section on an existing page, no existing
  behaviour changed, additive only. Per `.claude/rules/reusability-baseline.md`, no config-switch
  forks the call graph.
- **Feature flag**: none.
- **Backout plan**: remove the `GET /api/overview/program-board` handler from `overview.py` and the
  `ProgramLeaderboard` section from the `/overview` page; the rest of `/overview` (OVW-01's cards
  and adoption indicator) is unaffected since this story only adds a new section beneath them.
- **Success signal**: a CIO session's `GET /api/overview/program-board` returns 200 with correctly
  ordered items in < 300ms p95; a non-CIO session gets 403 with no data body; verified in staging
  before wider rollout.

## Documentation requirements

- **README updates**: `README.md` API table — add a `GET /api/overview/program-board` row (request,
  response shape, pagination defaults/clamp, 403/empty-list cases), matching the existing
  `/api/overview/summary` and `/api/overview/program-detail/*` row format.
- **Runbook**: none.
- **API reference**: FastAPI's generated `/docs` (OpenAPI); the new response schema documents
  itself, no separate file.
- **Inline code comments**: `app/api/overview.py` — new route's docstring must note (a) the
  JSONB sparkline validation/fallback contract (research C-2), and (b) the MoM neutral-state
  rule for <2 data points (research C-3), so a future edit doesn't silently drop either guard.
- **Examples / how-to**: none.

## Open questions

None — the five PRD-vs-mockup divergences raised by the Phase-2 mockup extraction were resolved
with the product owner on 2026-09-18, before `/arh-plan-implementation`. Resolutions below; they
are binding on PLAN.md.

## Resolved questions

| # | Question | Resolution | Basis |
|---|---|---|---|
| 1 | `metrics` shipped four bare value strings, diverging from OVW-01's `orgKpis` and PGD-01's `summary` | **Align with ADR-0007** — `metrics` is now an ordered 4-entry `[{glyph, label, value}]` array (FR-1 updated) | The mockup binds `{icon, label, value}` per entry via `sc-for`, so labels are template-bound, not hardcoded; two sibling precedents on the same page already ship server-owned constants |
| 2 | Is `icon` redundant on the wire, derivable from `type`? | **Keep `icon`** — no FR change | `DESIGN.md`'s "derivable" finding was a misdiagnosis: `apps/web/src/lib/programStyle.ts` derives *colors* from `type`, not the avatar letter. PGD-01 already ships the same field (`services/api/app/schemas/program_detail.py:12`) |
| 3 | The mockup renders no pager, no count, no sentinel — does the paging contract survive? | **Keep the API contract, render page 1 only** — endpoint stays paginated (default 20, clamp 100); the UI ships no pager | `.claude/rules/performance-baseline.md` requires pagination on every list endpoint, and NFR-004 targets growth; rendering only page 1 invents no UI the mockup lacks (CLAUDE.md § Design system) |
| 4 | `hint-placeholder-count="6"` contradicts a `page_size` default of 20 | **Render 6 skeleton rows regardless of `page_size`** | The attribute is a loading hint, not a count promise; 6 is what the design source specifies |
| 5 | The `flat` / `null` change-indicator state has no design source (mockup's `up = mom >= 0` is binary) | **Accept `DESIGN.md`'s conservative default** — neutral chip `#5b6472` on `#f0f1f4`; the chip is omitted entirely when `mom_change_percent` is `null` | Collapsing `flat` into `up` would render a genuinely flat program as improving. This remains the one value in `DESIGN.md` not drawn from the design source, now explicitly owner-approved |

Carried forward, not resolved here: `DESIGN.md`'s contrast audit records that all four type-chip
pairs and both month-over-month chip pairs fail WCAG AA (3.02–4.35:1) against NFR-accessibility.
This is systemic to the design's tint-on-tint chip recipe and already shipped in
`ProgramContext.tsx` and `ReleasesList.tsx` — a standing design-system issue, accepted at the
Product Gate, explicitly out of scope for this story.

Decisions logged in `docs/stories/OVW-04.md` § Decision log.

## Approvals

- **2026-09-18** — Pratik Pawar (PO + Designer + BA, single-approver mode covers all): **APPROVE**
  - Feature Summary, FRs, User Flows reviewed
  - UI specs pending in `DESIGN.md` (ux-agent, Phase 2) — Screen inventory above is authoritative
    input for that step
  - Edge Cases, Open Questions, test-case completeness reviewed
  - No-placeholder check ✓ · `[NEEDS CLARIFICATION]` count=0
  - Research verdict GO (all 3 conditions addressed in § Addressing Research Conditions)
  - Tracker subtask: pratikpawar009/Dashboard#467 (research). PRD subtask is filed by
    `/arh-plan-requirements` Phase 3 (`tracker_prd`), not yet run at this Phase 1 checkpoint.

- **2026-09-18** — Pratik Pawar (PO + Designer + BA, single-approver mode): **APPROVE** (Product Gate)
  - Gate surfaced via `/arh-plan-requirements` Phase 4; approved with the 5 § Open questions
    knowingly carried into `/arh-plan-implementation` as items to settle during planning, not as
    blockers on the PRD.
  - Test-case coverage audit PASS (12 cases, `coverage_audit.uncovered == []`), pre-push secret
    scan clean, no-placeholder check clean, `[NEEDS CLARIFICATION]` count 0.
  - WCAG AA chip-contrast finding accepted as a standing design-system carry-forward, not a
    change request against this story.
  - Tracker: story #22 · research #467 · plan-requirements #468.

- **2026-09-18** — Pratik Pawar (PO): **APPROVE** (clarification-gate resolution)
  - Resolved all 5 § Open questions ahead of `/arh-plan-implementation`, per
    `phase-preconditions` § Clarification gate (open questions cannot cross a phase boundary).
  - One shape change accepted into FR-1: `metrics` becomes an ordered 4-entry
    `[{glyph, label, value}]` array per ADR-0007. The other four resolved without FR changes.
  - See § Resolved questions for each resolution and its basis.

