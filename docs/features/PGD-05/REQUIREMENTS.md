# Feature: PGD-05 — Project team table + per-member usage popup

## Problem
A signed-in user viewing a program's Program Detail page cannot see who is driving AI usage
on the program, nor drill into an individual member's usage without leaving the page. The
mockup's team table has no backing data, and there is no way to inspect one member's
contribution in detail.

## Outcome
`GET /api/overview/program-detail/{program_id}/team?range=` returns one row per program
member active in the selected range (`member_name, role, sessions, tokens,
avg_tokens_per_session`), enabling the mockup's team table to render. A per-member usage
popup, gated by its own authorization check, renders `personal-usage-api`'s `{cards,
daily_tokens, commands}` verbatim for a member the requester is authorized to view.

## Constraints
- Must reuse the `overview` router (`services/api/app/api/overview.py`,
  `prefix="/api/overview"`) — a new router is out of scope (PGD-01..04 precedent).
- `program_members` is a to-date snapshot with no temporal columns (`ix_program_members_program_id`
  only) — range-scoped `sessions`/`tokens`/`avg` require aggregating range-filtered
  `usage_events`, not a read of `program_members` alone (research Risk #1).
- NFR-002 perf budget (≤2s range refresh) inherited from PGD-01..04 precedent.
- **Design gate**: the popup (AC-9..12) has no mockup backing it. `docs/features/PGD-05/DESIGN.md`
  § "Screen 2" documents that the PGD mockup (`docs/design/mockups/Program Detail.html`) contains
  no popup/modal/overlay/dialog and no clickable team rows, and that SHP-02 ships the
  `GET /api/personal-usage/{user_id}` endpoint only — no popup/modal component exists anywhere in
  `apps/web/src` (SHP-02 `state.json` records `design: "n/a"`; its PRD § Scope "Out:" defers all
  `apps/web` component work rendering cards/chart/commands to ARC-01/DEV-01/PMD-01). **The row
  trigger, modal chrome, and denied(403)/loading/error states for the popup are undesigned by any
  mockup. `/arh-iterate-design PGD-05` MUST run and produce a designed popup (trigger, chrome,
  and all four states) before AC-9..12 can be planned or implemented.** The team-table endpoint
  and its UI (AC-1..8) are unaffected and may proceed without this gate.

## Solution sketch
Add a fifth sibling endpoint to the `overview` router, following PGD-01..04's exact shape:
`program_visibility()` gate → `_range_with_default()` → a new `fetch_program_team()` service
function that issues two SELECTs — one `program_members` snapshot read, one range-scoped
`usage_events` aggregate joined by `user_id`/`program_id` — computes `avg_tokens_per_session`
server-side, orders descending by `tokens`, and returns a new `ProgramTeamResponse` envelope.
The team table renders these rows on the Program Detail page. Separately, PGD-05 builds a
per-member usage popup component — a row trigger opens a modal that calls `personal-usage-api`
(`GET /api/personal-usage/{user_id}`, SHP-02) for the clicked member and renders its `{cards,
daily_tokens, commands}` response verbatim, gated by a story-local `member_in_program_visibility`
check distinct from SHP-02's own gate. The popup's visual design is pending
`/arh-iterate-design PGD-05` per the Constraints design gate above.

## Addressing Research Conditions
- **C-1 (index for range-scoped queries)**: New Alembic migration adds
  `Index("ix_usage_events_program_id_user_ts", "program_id", "user", "ts")` on `usage_events`
  to support the range+member-scoped aggregate without a full-table scan. A perf test
  (`services/api/tests/perf/test_program_team_perf.py`, mirroring PGD-02/03/04 precedent) asserts
  a bounded query count (exactly two SELECTs per request — no Cartesian join) and duration
  ≤2s under NFR-002. See PGD-05-FR-1.
- **C-2 (popup relay vs direct)**: Live decision, owned by this story. The popup calls
  `personal-usage-api` (`GET /api/personal-usage/{user_id}`, SHP-02) directly from the
  frontend via the standard ADR-0008 server-to-server proxy pattern (matching PGD-01/02/03's
  `/api/proxy/*` route handlers) rather than relaying through a new PGD-05-owned endpoint —
  there is no PGD-05-specific transformation of SHP-02's response (AC-10: rendered verbatim), so
  a relay endpoint would add a hop with no contract value. This decision is independent of the
  design gap in § Constraints: the wiring (which endpoint, which proxy pattern) is settled here;
  only the popup's visual chrome and states await `/arh-iterate-design`.
- **C-3 (decision log entries)**: Five assumptions already logged in
  `docs/stories/PGD-05.md` § Decision log (2026-08-26): (a) `member_name`/`role` are
  usage-derived from `program_members`, no manual roster enrichment in scope; (b) zero active
  members → empty list, not an error; (c) `avg_tokens_per_session` rounds to nearest integer;
  (d) row ordering is descending by `tokens`; (e) BED-03's `program_members` rebuild is
  synchronous on every ING-02 ingest, so the table reflects live data at query time — no async
  rebuild coordination needed. All five carry provenance per `clarification-marker` discipline;
  none are silent guesses.
- **C-4 (response schema exact)**: `ProgramTeamResponse` is `{items: [ProgramTeamRow]}`, where
  `ProgramTeamRow = {member_name: str, role: str, sessions: int, tokens: int,
  avg_tokens_per_session: int}`, field order locked as listed, sourced from
  `docs/stories/PGD-05.md` AC-1/FR-PD-13/14 + mockup team-table column order (Program Detail
  mockup, `<!-- TEAM -->` section, per research Exploration Log). No additional fields. See
  PGD-05-FR-2.
- **C-5 (PLAN.md file plan uses real paths)**: `/arh-plan-implementation` MUST use
  `services/api/app/api/overview.py` (new route), `services/api/app/services/program_team.py`
  (new service module, `fetch_program_team()`), and `services/api/app/schemas/program_detail.py`
  (extended with `ProgramTeamRow`/`ProgramTeamResponse`) — not invented or placeholder paths.
  This PRD names them here so PLAN.md inherits them verbatim.

## Scope
- In: `GET /api/overview/program-detail/{program_id}/team?range=` endpoint — range validation,
  `program_visibility` RBAC gate, two-SELECT aggregation (`program_members` snapshot +
  range-scoped `usage_events`), server-side `avg_tokens_per_session` computation,
  `ProgramTeamResponse` envelope, structured logging.
- In: New Alembic migration adding the `(program_id, user, ts)` composite index on
  `usage_events`.
- In: Team table UI on the Program Detail page (rows render `member_name, role, sessions,
  tokens, avg_tokens_per_session`).
- In: **The per-member usage popup component itself** — PGD-05 builds this component; it does
  NOT reuse a pre-existing SHP-02 component (SHP-02 ships only the
  `GET /api/personal-usage/{user_id}` endpoint — its own PRD § Scope "Out:" defers all
  `apps/web` component work to ARC-01/DEV-01/PMD-01). The popup renders `personal-usage-api`'s
  `{cards, daily_tokens, commands}` verbatim (AC-10), behind the row trigger, gated by
  `member_in_program_visibility` (AC-9, AC-11, AC-12). **Blocked on the design gate in
  § Constraints** — `/arh-iterate-design PGD-05` must produce the trigger, modal chrome, and
  denied/loading/error states before this half of scope can be planned or implemented.
- In: Next.js proxy route(s) needed to reach the new endpoint and to relay
  `personal-usage-api` for the popup, matching PGD-01/02/03's ADR-0008 pattern.
- Out: Manual roster enrichment of `member_name`/`role` (research Risk #2) — usage-derived only,
  a future story's scope.
- Out: Persona-branching on the team-table response — `program_visibility` is open-aggregate by
  contract (AC-6, A-004), byte-identical across personas for the same `program_id`/`range`.
- Out: Changes to `program_members` table writes (BED-03 owns the rebuild; this story reads only).

## Functional requirements

FRs trace 1:1 to story ACs; see `docs/stories/PGD-05.md` for canonical wording.
New impl constraints introduced below:

**PGD-05-FR-1** — Range-scoped aggregation query shape  *(extends AC #1/#3 with: exact query
strategy + required index)*

The service issues exactly two SELECTs per request: one `program_members` snapshot read
(for the roster of members active in the program) and one range-scoped `usage_events`
aggregate (`GROUP BY user_id`, filtered `program_id` + `ts` within the resolved window) —
never a join producing a Cartesian product. The aggregate query relies on a new composite
index `(program_id, user, ts)` on `usage_events` (Alembic migration, this story). A perf test
asserts the two-query bound and a ≤2s duration under NFR-002.

**PGD-05-FR-2** — Response schema field order and types  *(extends AC #1 with: exact schema)*

`ProgramTeamResponse = {items: [ProgramTeamRow]}`. `ProgramTeamRow` fields, in this exact
order: `member_name: str`, `role: str`, `sessions: int`, `tokens: int`,
`avg_tokens_per_session: int` (rounded to nearest integer server-side, never `float`). No
additional fields. Rows ordered descending by `tokens`.

**PGD-05-FR-3** — Popup authorization gate is story-local  *(extends AC #9/#11/#12 with: exact
gate name and denial contract)*

The popup is gated by `member_in_program_visibility` (`program_visibility` AND (self OR cio)) —
a check distinct from and never delegated to SHP-02's own `individual_usage_visibility` gate on
`personal-usage-api` (`docs/requirements/api.md` `authz_note`). A denied request is logged as
`member_view_denied` (not `individual_view_denied`), returns `HTTP 403`, and the response body
carries no personal-usage fields (cards, daily_tokens, commands) — denial and data are mutually
exclusive.

## Non-functional requirements

- Performance: range/filter-change refresh ≤2s (NFR-002, sourced from story). Query-count
  bound of exactly two SELECTs per team-table request, per `.claude/rules/performance-baseline.md`
  (no N+1, no unbounded fan-out).
- Security: Per `.claude/rules/security-baseline.md`: applies to the team-table and popup
  surfaces in scope. Team table enforced server-side via `program_visibility` (open-aggregate,
  NFR-005). The popup is gated via `member_in_program_visibility` (PGD-05-FR-3), distinct from
  SHP-02's `individual_usage_visibility` gate on the same `personal-usage-api` endpoint. Every
  check outcome logged per `rbac-checks` (`member_view_denied` for popup denials). Underlying
  `program_members` rows are classified Confidential.
- Accessibility: Per `.claude/rules/accessibility-baseline.md`: applies to the team-table and
  popup UI. WCAG AA (NFR-008) — table has proper header cells (`<th scope="col">`) and is
  screen-reader navigable. The row **trigger** that opens the popup must expose an accessible
  name and be keyboard-operable (NFR-008) — its concrete visual/interaction design is pending
  the design gate in § Constraints, but the obligation itself belongs to PGD-05, not a
  follow-on story.
- Observability: No dedicated team-table-view event in NFR-011's event set — the page-level
  `program_drilldown` event (PGD-01, on page load) is treated as covering this widget's view
  (2026-08-26 assumption, sourced from story). Popup denials are logged as `member_view_denied`
  with `{user_id, target_member_id}` (`rbac-checks` contract).

## Screen inventory

| Screen | Route | Render | Primary purpose | States | Story ACs covered |
|---|---|---|---|---|---|
| Program Detail — Team table | `/program-detail/[program_id]` (existing page, new panel) | server (initial fetch) + client (range switch) | Show one row per active program member (name, role, sessions, tokens, avg/session) for the selected range | Populated / Loading / Empty (zero active members) / Error | AC-1, AC-2, AC-3, AC-4, AC-5, AC-6, AC-7, AC-8 |
| Member usage popup | modal over `/program-detail/[program_id]` (no own route) | client | Show one member's `personal-usage-api` data (cards, daily tokens, commands) verbatim, opened via row trigger | Populated / Loading / Denied (403, no data) / Error | AC-9, AC-10, AC-11, AC-12 |

## Visual spec

See [DESIGN.md](./DESIGN.md) — Screen 1 (team table) is extracted from
`docs/design/mockups/Program Detail.html` § `<!-- TEAM -->`. Screen 2 (member usage popup) is
**not present in any mockup** — `DESIGN.md` § "Screen 2" records the evidence; the popup's
trigger, chrome, and states must be designed via `/arh-iterate-design PGD-05` before AC-9..12
are planned or implemented (see § Constraints).

## Rollout plan
- **Strategy**: bang-bang — additive read-only endpoints plus new UI on an existing page; no
  client currently depends on the response shape (first consumer).
- **Feature flag**: none.
- **Backout plan**: revert the router addition, the new UI panel, and the popup component;
  revert the Alembic migration (new index only, no column/table changes — safe to drop without
  data loss).
- **Success signal**: endpoint returns range-differentiated team data in production smoke
  traffic within the ≤2s NFR-002 budget; popup opens and renders `personal-usage-api` data for
  an authorized requester with no regression in PGD-01..04 latency on the shared `overview`
  router.

## Documentation requirements
- **README updates**: `README.md` API table — add a `GET
  /api/overview/program-detail/{program_id}/team` row alongside the existing
  `program-detail`/`token-trend`/`releases`/`commands` rows, documenting the two-SELECT query
  shape and the zero-members empty-list behavior; note the popup's reuse of
  `personal-usage-api` under `member_in_program_visibility`.
- **Runbook**: none.
- **API reference**: FastAPI `/docs` (auto-generated) covers the route; no separate reference
  needed.
- **Inline code comments**: `fetch_program_team()` service function — docstring noting the
  two-SELECT strategy (snapshot + range-scoped aggregate) and the new composite index it
  depends on; popup component — comment noting `member_in_program_visibility` gate and that it
  renders `personal-usage-api`'s response verbatim with no reshaping.
- **Examples / how-to**: none.

## Open questions
None. The popup relay-vs-direct question (former Open question, research Risk #3) is resolved
in § Addressing Research Conditions C-2. The remaining popup design work is not an open
question — it is a hard design gate recorded in § Constraints and § Scope.

Decisions logged in `docs/stories/PGD-05.md` § Decision log.

## Change requests
- **2026-09-17 (round 1)** — Product Gate returned CHANGES: resolve the popup design gap.
  § Scope falsely claimed PGD-05 reuses "SHP-02's existing personal-usage popup component";
  verified SHP-02 is backend-only (`design: "n/a"`, no popup/modal component anywhere in
  `apps/web/src`) and its own PRD defers all `apps/web` component work to
  ARC-01/DEV-01/PMD-01. The popup (AC-9..12) has no mockup (`DESIGN.md` § "Screen 2" — the PGD
  mockup has no popup and no clickable rows; the EMD mockup's popup is a different epic
  rendering a different response shape), no reusable component, and no designed
  trigger/denied/loading/error states, despite NFR-008 obligating an accessible, keyboard-
  operable trigger.
- **2026-09-17 (round 2, rejected)** — First resolution attempt deferred AC-9..12 to a new
  follow-on story `PGD-05a` (option b). The user rejected this on review; reversed. Three
  verified collisions with `docs/requirements/RTM.md`: (1) RTM's 2026-08-26 Decisions entry
  already applied a vertical-slice test and folded FR-AUTH-08 into PGD-05 specifically because
  a standalone popup story "would produce zero new contract shape, which is the phantom-story
  smell this schema's `produced_by` rule exists to catch" — a deferred `PGD-05a` re-creates
  exactly that rejected story; (2) `PGD-05a` is not a valid id — RTM uses sequential sibling
  numbering (PGD-01..06) with no `-a` suffix anywhere in the repo, and the id appeared in no
  RTM row, no `features.json` entry, and no tracker issue; (3) deferring would have stranded
  the RTM row, `docs/stories/PGD-05.md`, `docs/requirements/api.md`'s `personal-usage-api`
  `authz_note`, and tracker #27 — all of which still claim the popup — leaving FR-AUTH-08
  covered by nothing.
- **2026-09-17 (round 3, resolution taken)** — Option (a): restore PGD-05 to its full original
  scope (team table + popup, AC-1..12, FR-1..3) and resolve the design gap *within* that scope
  instead of deferring it. § Scope now states plainly that PGD-05 builds the popup component
  itself (SHP-02 supplies the endpoint only) and gates its start on `/arh-iterate-design
  PGD-05` for the trigger, modal chrome, and denied/loading/error states. § Constraints carries
  the design-gate requirement so it cannot be missed. § Addressing Research Conditions C-2 is
  live again (relay-vs-direct decided: direct call via ADR-0008 proxy pattern). FR-3, the
  Security/Accessibility/Observability NFRs, and the Screen inventory's popup row are all
  restored. `PGD-05a` is referenced in this changelog entry only, as the record of a rejected
  proposal; no other section of this PRD refers to it.

## Approvals
- **2026-09-17** — Pratik Pawar (PO + Designer + BA, single-approver mode): **APPROVE**
  - Recorded at the Product Gate (Phase 4), in the approver's own voice. Verdict collected
    interactively across two rounds; drafting did not self-approve.
  - Round 1 returned **CHANGES** (resolve the popup design gap). Round 2 approved after the
    option-(b) deferral to `PGD-05a` was rejected and reversed — see § Change requests.
  - Feature Summary, FRs (PGD-05-FR-1..3), and User Flows reviewed; AC-1..12 in scope.
  - UI specs: `docs/features/PGD-05/DESIGN.md` is complete. Screen 1 (team table) is fully
    specified from the PGD mockup. Screen 2 (member usage popup) is backed by no mockup and
    is approved **subject to the design gate** in § Constraints: `/arh-iterate-design PGD-05`
    must run before AC-9..12 are planned or implemented. AC-1..8 are unblocked.
  - Edge Cases + Open Questions reviewed (0 open); test cases 18/18 automatable,
    coverage audit uncovered=[]
  - No-placeholder check ✓ · `[NEEDS CLARIFICATION]` count=0
  - Research verdict GO-WITH-CONDITIONS — all 5 conditions addressed above
  - Tracker subtasks: #443 (research), #444 (plan-requirements)
