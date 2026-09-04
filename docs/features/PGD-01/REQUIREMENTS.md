# Feature: PGD-01 — Program Detail page shell: header, summary cards, switch/back nav

## Problem

CIOs and Engineering Managers can see every program on the Adoption Overview board but have no
way to drill into a single program: no Program Detail page, no backing endpoint, no way to move
between programs without losing their place. Comparing one program's to-date adoption numbers
today means manually correlating board rows — there is no per-program view at all.

## Outcome

Any authenticated session opens `/programs/[program_id]` and sees that program's header (icon,
name, type tag, description) and 7 to-date summary cards, populated from
`GET /api/overview/program-detail/{program_id}`. They can switch to another program in place, or
return to the board via "← Back to program board". The response is byte-identical regardless of
which persona requested it (FR-PD-17).

## Constraints

- **Hard prerequisite (research Risk #9 / CF-05 on `docs/features/AUTH-04/state.json`)**:
  `services/api/app/api/programs.py:132` (AUTH-04, shipped, `review: PASS`) emits
  `href=f"/api/overview/program-detail/{row.program_id}"` — a JSON API path. The mockup binds
  `href` as a page-navigation target and ADR-0005 §2 derives the switcher's active row by
  comparing `href` to the current route. Until AUTH-04 emits `href=f"/programs/{row.program_id}"`
  (and TC-07's assertion at `services/api/tests/unit/test_programs.py:604` is updated to match),
  FR-4's switcher navigation cannot succeed.
  **Decided 2026-09-03 by the user at the Product Gate: this fix is folded into PGD-01's own
  implementation** rather than shipped as a separate `bugfix/AUTH-04` PR. PGD-01's branch therefore
  carries a two-line change to a story that is already `review: PASS` — an accepted, recorded
  exception to `.claude/rules/surgical-changes.md`, not an oversight. `/arh-plan-implementation`
  must give it its own task and its own DECISIONS.md entry so the AUTH-04 edit is reviewable on its
  own terms inside PGD-01's diff, and `/arh-review` must be told to expect it.
- **Program visibility stays open-aggregate** (`program_visibility`, AUTH-03/`rbac-checks`): any
  authenticated session may load any program's detail; this story adds no per-program membership
  gate. The switcher *list* stays membership-scoped upstream by AUTH-04 (PRD line 528,
  FR-AUTH-10) — the asymmetry between an unscoped detail endpoint and a scoped switcher list is
  intentional (Clarification C-3). PRD R-003/Q-001 (the resulting risk) stays open, owned by
  `/arh-security-review`, not this story.
- `program-detail-api` is a sealed contract consumed by ARC-01, DEV-01, PMD-01, EMD-01 — any field
  change to the response ripples to four downstream features not built yet.
- Values arrive server-side pre-formatted (`docs/design/README.md` § "Values arrive
  pre-formatted"): all 7 numeric card values pass through `format_number()`
  (`services/api/app/utils/format.py:74`, BED-02/`api-conventions`) before serialization; the
  frontend never formats a raw number.
- `docs/design/mockups/Program Detail.html` is the UI contract (`CLAUDE.md`) for the header and
  summary cards. The same mockup also shows Daily Token Consumption, Releases, Commands, and Team
  sections below the cards — those are PGD-02/03/04/05 and PGD-06 (session chart), out of scope
  here (Clarification C-1).
- Desktop-only design — the mockup carries no responsive breakpoints (`docs/design/README.md`);
  no mobile layout exists for this shell.

## Solution sketch

A new FastAPI router (`app/api/overview.py`) exposes `GET /api/overview/program-detail/{program_id}`,
gated by the existing `program_visibility` open-aggregate check, reading one `program_summary` row
(BED-01/`db-schema`), formatting all 7 metrics server-side, and returning header + summary-card
fields with no persona branching; an unknown id returns `404` with the app's standard error
envelope. A new Next.js route `/programs/[program_id]` renders `ProgramDetailHeader` (avatar,
name, type chip, description, "← Back to program board" link, "Switch program" selector sourced
from `GET /api/programs`) and `ProgramSummaryCards` (7-card grid) from that response, reloading
both components in place when the switcher selection changes.

## Addressing Research Conditions

Research verdict GO-WITH-CONDITIONS (82/100). `docs/research/PGD-01.md` §
"Conditions for Downstream (GO-WITH-CONDITIONS)" carries 5 numbered conditions:

1. **Scope boundary (settled, C-1)** — mitigated in Constraints/Scope: shell = header + 7 summary
   cards + "Switch program" selector + "← Back to program board" link, per user-confirmed
   Clarification C-1 (2026-09-03). Daily token chart, releases, commands, team table, and session
   chart are listed under Scope § Out against PGD-02/PGD-03/PGD-04/PGD-05/PGD-06, never inlined
   here.
2. **Frontend route (settled, C-2)** — mitigated: `/programs/[program_id]`, fixed in Scope and
   Screen inventory, plural to match the `/api/programs` collection and the Next.js App Router
   item-route convention.
3. **Program visibility (settled, C-3)** — mitigated: stated as fact in Constraints, not
   re-litigated. Detail is intentionally unscoped; only the switcher list is membership-scoped
   (upstream, AUTH-04).
4. **AUTH-04 `href` fix — hard prerequisite (new, Risk #9 / CF-05)** — mitigated: recorded as a
   Constraint and as a Rollout-plan dependency. Folded into PGD-01's implementation by the user's
   Product Gate decision (2026-09-03), as its own task with its own DECISIONS.md entry, rather than
   a separate `bugfix/AUTH-04` PR.
5. **Downstream validation (unchanged)** — mitigated: FR-PD-17's byte-identical invariant and the
   Rollout plan's success signal both require test fixtures asserting the response schema against
   what ARC-01/DEV-01/PMD-01/EMD-01 each expect, planned in `/arh-plan-implementation` before
   those four features build on this contract.

### Resolved questions

Research `docs/research/PGD-01.md` § Clarifications — all three user-confirmed 2026-09-03, not
reopened here:

| # | Question | Resolution |
|---|---|---|
| C-1 | Does the shell include only header + 7 cards, or the sections below? | Header + 7 cards + switcher + back link only. |
| C-2 | Route path — `/program/[id]` or `/programs/[id]`? | `/programs/[program_id]`. |
| C-3 | Is open-aggregate visibility final, or does this story add membership scoping? | Open-aggregate, unchanged; no scoping added here. |

## Scope

**In:**
- `GET /api/overview/program-detail/{program_id}`: header (icon, name, type, description) + 7
  to-date summary cards (tokens, features, releases, repos-with-Harness-installed, commands
  executed, lines of code generated, user stories delivered), all values server-formatted, `404`
  JSON error body for an unknown id, byte-identical across personas.
- `/programs/[program_id]` Next.js route rendering `ProgramDetailHeader` (avatar, name, type
  chip, description, "← Back to program board" link, "Switch program" selector) and
  `ProgramSummaryCards` (7-card grid).
- Switch-program selector, populated by `GET /api/programs` (AUTH-04, persona-scoped), reloading
  header + summary-card data in place on selection — no full page navigation.
- "← Back to program board" link, navigating to the Adoption Overview page.
- Structured JSON log events `program_drilldown` (page open) and `program_switch` (switcher
  selection).

**Out:**
- Daily token consumption chart and range toggle — deferred to PGD-02.
- Releases via Harness table — deferred to PGD-03.
- Commands executed panel — deferred to PGD-04.
- Project team table — deferred to PGD-05.
- Session chart / member-command popup — deferred to PGD-06.
- ~~The AUTH-04 `href` bugfix itself~~ — moved IN scope by the Product Gate decision of 2026-09-03
  (Constraints). It is built here, as a discrete task, and remains tracked as CF-05 on AUTH-04.
- Program-membership scoping on the detail endpoint — explicitly out per Clarification C-3;
  revisited, if ever, by `/arh-security-review` (R-003/Q-001).
- Mobile/responsive layout — mockup is desktop-only.

## Functional requirements

FRs trace 1:1 to story ACs; see `docs/stories/PGD-01.md` for canonical wording. New impl
constraints introduced below:

**PGD-01-FR-1** — Endpoint path and RBAC call shape *(extends AC1 with: exact route and RBAC call)*

`GET /api/overview/program-detail/{program_id}` lives in a new module `app/api/overview.py`; a
single `select()` against `program_summary` (BED-01/`db-schema`), no N+1. `program_visibility`
is called once with the real `program_id` (unlike `app/api/programs.py`'s sentinel-argument
pattern, which has no per-resource id to pass) — the check still passes unconditionally for any
authenticated session, per the open-aggregate contract (`rbac-checks`).

**PGD-01-FR-2** — Numeric formatting and the repos ratio field *(extends AC3 with: which
formatter, applied where, and the one non-magnitude value)*

The 6 magnitude metrics (tokens, features, releases, commands, LOC, stories) pass through
`format_number()` (`app/utils/format.py`, BED-02) before being placed on the response.
`repos_with_harness_installed` renders as `"{repos_with_harness_installed} / {repos_total}"`
(e.g. `"5 / 6"`) per the mockup's `s.value` binding and the `repos_total` column already present
on `ProgramSummary` (`app/models/rollup.py`) — not run through `format_number()`, since it is a
small-int ratio, not a magnitude value.

**PGD-01-FR-3** — 404 error contract *(extends AC7 with: exact envelope)*

An unknown `program_id` returns `404` via the existing single error envelope
(`app/core/errors.py`): `{"error": {"code": "http_404", "message": ..., "details": ...}}` — the
same shape every other exception handler in the codebase already produces; no new envelope shape
introduced.

**PGD-01-FR-4** — Switcher reload without page navigation *(extends AC5 with: mechanism and its
AUTH-04 dependency)*

Selecting an entry in "Switch program" re-fetches `GET /api/overview/program-detail/{new_id}`
client-side and re-renders `ProgramDetailHeader` / `ProgramSummaryCards` in place; the URL updates
to `/programs/{new_id}` via client-side routing, not a full document reload. This depends on the
AUTH-04 `href` fix (Constraints) — until it lands, `o.href` points at a JSON path and cannot serve
as the navigation target.

**PGD-01-FR-5** — Observability event shapes *(extends NFR-011 with: field shape)*

`program_drilldown` logs once per page load with `{program_id}`; `program_switch` logs once per
switcher selection with `{from_program_id, to_program_id}`. Both are structured JSON via the
existing `JSONFormatter` (`app/core/logging.py`); no PII in either event.

## Non-functional requirements

- Performance: page render ≤3s under normal load (story NFR-001). Per
  `.claude/rules/performance-baseline.md`: the endpoint issues one bounded `select()` against
  `program_summary`, no unbounded fan-out; the switcher's `GET /api/programs` call is a separate,
  already-scoped request this story does not add queries to.
- Security: Per `.claude/rules/security-baseline.md`: applies to the new endpoint. Feature-specific:
  bearer-JWT required (`get_current_user`); `program_visibility` gates every request (story
  NFR-005), no client-side-only gating; the response carries only header + 7 summary-card fields,
  never `session.programs` or other cross-program data.
- Accessibility: Per `.claude/rules/accessibility-baseline.md`: applies to the new header, cards,
  selector, and back-link. Story softens the baseline to WCAG 2.1 AA "where feasible" (story
  NFR-008), carried here verbatim.
- Observability: `program_drilldown` and `program_switch` structured JSON log events (FR-5); no
  additional metrics/tracing budget beyond existing app-wide logging.

## Screen inventory

Scoped to the shell's four in-scope regions on the Program Detail mockup
(`docs/design/mockups/Program Detail.html`, PGD epic per `docs/design/schema.json`). Daily Token
Consumption / Releases / Commands / Team sections shown in the same mockup belong to PGD-02..06
and are excluded from this inventory.

| Screen | Route | Render | Primary purpose | States | Story ACs covered |
|---|---|---|---|---|---|
| Program Detail header | /programs/[program_id] | server (initial load) + client (switcher reload, FR-4) | Program avatar (`prog.avatar`/`avatarStyle`), name, type chip (`prog.typeChip`/`prog.ptype`), description (`prog.scope`), "← Back to program board" link | Populated / Loading (switcher fetch in flight) / Error (unknown `program_id` → 404) | AC2, AC4 |
| Switch program selector | — (embedded in header, same route) | client | Dropdown button + option list from `GET /api/programs`; each option shows dot colour, label, current-selection check | Closed / Open / Populated (option list) | AC5 |
| Program summary cards | /programs/[program_id] | server (initial load) + client (switcher reload) | 7-card grid: glyph, pre-formatted value, label, per the `summary` binding (`hint-placeholder-count="7"`) | Populated / Loading (switcher fetch in flight) / Error (404 → error state, not a blank shell) | AC3, AC7 |
| Back-to-board navigation | /programs/[program_id] → Adoption Overview route | client | "← Back to program board" link target | Populated only | AC4 |

## Visual spec

See [DESIGN.md](./DESIGN.md) — hand-authored from the decoded PGD mockup (`ux-agent` is not installed in this repo).

## Rollout plan

- **Strategy**: bang-bang — new route + new endpoint, no existing behaviour changed, low blast
  radius (additive-only). Per `.claude/rules/reusability-baseline.md`, no config-switch is
  introduced to fork the call graph.
- **Feature flag**: none.
- **Backout plan**: remove the `/programs/[program_id]` route and the `overview.py` router
  registration; no schema or data migration to unwind (read-only against the existing
  `program_summary` table).
- **Success signal**: `program_drilldown` events firing for real page loads with zero 5xx from the
  new endpoint over the first 48h in production; downstream integration test fixtures for
  ARC-01/DEV-01/PMD-01/EMD-01 (condition 5) passing against the live schema before those features
  build on it; AUTH-04's `href` fix (condition 4) merged and the switcher's active-row match
  verified end-to-end.

## Documentation requirements

- **README updates**: `README.md` API table — add a `GET /api/overview/program-detail/{program_id}`
  row (path, request, response shape, 404 case), matching the existing `/api/programs` row format.
- **Runbook**: none.
- **API reference**: FastAPI's generated `/docs` (OpenAPI); no separate file — the
  `ProgramDetailResponse` Pydantic model documents the schema automatically.
- **Inline code comments**: `app/api/overview.py` — module docstring noting the byte-identical
  response invariant (FR-PD-17) and the AUTH-04 `href` dependency (Constraints), matching the
  documentation style already used in `app/api/programs.py`. `apps/web/src/app/programs/[program_id]/page.tsx`
  — comment documenting the switcher's client-side-reload contract (FR-4).
- **Examples / how-to**: none.

## Open questions

<!-- None open. C-1/C-2/C-3 (scope, route, visibility) were resolved 2026-09-03 by the user      -->
<!-- during /arh-research Phase 2 follow-up -- see docs/research/PGD-01.md § Clarifications and   -->
<!-- this PRD's § Addressing Research Conditions / Resolved questions. PRD R-003/Q-001 (the        -->
<!-- open-aggregate visibility risk) stays open but is owned by /arh-security-review, not this     -->
<!-- story (C-3) -- not counted here.                                                              -->
<!-- needs_clarification_count: 0.                                                                 -->
<!--                                                                                                -->
<!-- Kept as a comment deliberately, matching docs/features/SHP-01/REQUIREMENTS.md: the             -->
<!-- phase-preconditions clarification gate treats ANY non-blank, non-comment line in this          -->
<!-- section as an unresolved open question and aborts the next phase. Prose saying "None" trips    -->
<!-- it.                                                                                             -->
<!--                                                                                                -->
<!-- Decisions logged in docs/stories/PGD-01.md § Decision log (404 error-contract assumption) and  -->
<!-- docs/research/PGD-01.md § Clarifications (C-1/C-2/C-3).                                        -->

## Approvals

**APPROVED** — Pratik Pawar (pratik.pawar@apexon.com), 2026-09-03, via the `/arh-plan-requirements` Product Gate.

Every checklist item passed at approval. Three matters were accepted with eyes open rather than silently:

| Item | Status at approval | Why accepted |
|---|---|---|
| Test-case coverage audit | **PASS, with disclosed thinness** | A ≤4 test-case cap was an explicit instruction for this run. `coverage_audit.uncovered` is genuinely `[]` — all 16 ids are covered — but `coverage_audit.audit_notes` records two strains: NFR-security has no dedicated case (its clauses ride inside TC-01), and `program_switch`, half of FR-5's observability contract, is not independently tested because the PRD does not specify how the backend distinguishes a switcher fetch from an initial load. Revisit if that mechanism gets specified. |
| Designer approves UI specifications via `DESIGN.md` | **PRODUCED, hand-authored** | `ux-agent` is not installed in `.claude/agents/`, so Phase 2's design branch had no worker. `DESIGN.md` was written directly from the decoded PGD mockup instead, pre-implementation. It records three items the mockup does not settle: the static `CIO / CXO` persona chip (conflicts with AC-6), the back-to-board target (depends on the unbuilt OVW route), and AC-7's 404 error state (no mockup treatment). All three need a decision before the components are built. |
| AUTH-04 `href` fix folded into this story | **ACCEPTED EXCEPTION** | The Product Gate decision of 2026-09-03 puts a two-line change to a `review: PASS` story inside PGD-01's branch, against `.claude/rules/surgical-changes.md`. Taken deliberately to clear FR-4's prerequisite without a separate cycle. Mitigation: it gets its own task and its own DECISIONS.md entry in `/arh-plan-implementation`, so it is reviewable on its own terms. |

Carrying into `/arh-plan-implementation`: the three unsettled design items above, and the AUTH-04 edit as a discrete task.
