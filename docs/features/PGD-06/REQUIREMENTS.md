# Feature: PGD-06 — Daily session-time chart w/ member filter (backend)

## Problem
Program Detail has no data source for daily AI-coding session-time trends, org-wide or
per-member. `session_series` exists but nothing serves it.

## Outcome
`GET /api/overview/program-detail/{program_id}/session-time-series?range=&member_id=` returns
a zero-padded daily series (raw-int seconds) plus server-computed `period_total_seconds` and
`avg_seconds_per_day`, gated the same way PGD-05's `/team/{member_id}/usage` route already is.

## Constraints
- Must reuse the `overview` router (`services/api/app/api/overview.py`) — no new router.
- Reads `session_series` only; never writes it (BED-01/BED-03 own writes via `rollup_rebuild`).
- Must reuse `_range_with_default` / `validate_range` (BED-02 api-conventions) — no bespoke
  range parsing.
- Must reuse `program_visibility` and `member_in_program_visibility` from `rbac-checks`
  (AUTH-03) — no new gate logic.

## Solution sketch
Add an eighth sibling endpoint to `overview.py`. Because no `session_series` row ever carries
a null `member_id` (see Addressing Research Conditions, C-1), the org/program-wide series is
computed by summing `session_time_seconds` across all of a program's members per day — not by
querying a null-`member_id` row. `program_visibility` gates every request; a non-self
`member_id` additionally requires `member_in_program_visibility`, checked before the query runs
(mirroring PGD-05's popup route). Response is zero-padded to the range's fixed day count, with
`period_total_seconds`/`avg_seconds_per_day` computed server-side as raw ints, matching the
token-trend sibling.

## Addressing Research Conditions
- **C-1 (index verification)** — Corrected, not merely verified: the story's originally
  assumed `(program_id, member_id, date)` index does not exist. The only index touching these
  columns is the 4-column unique constraint `uq_session_series_org_id_program_id_member_id_date`
  on `(org_id, program_id, member_id, date)` (`app/models/rollup.py`). The org-wide query (no
  `member_id` filter, summed across members) does not benefit from the constraint's leading
  `member_id` position the way a single-member lookup would; it scans by `(org_id, program_id,
  date)`, a strict prefix-minus-one of the existing constraint. This is acceptable at current
  data volume (bounded by `member_id` cardinality × 90 days) but is NOT the same index shape
  Risk #4 assumed. No new migration is added by this story — see PGD-06-FR-2 for the query
  shape this constrains.
- **C-2 (frontend formatter availability)** — Moot. PGD-06 ships backend-only (see Scope); no
  frontend code, and therefore no formatter dependency, ships in this story.
- **C-3 (gate-before-query test)** — Adopted as-is: test strategy must assert
  `member_in_program_visibility` is invoked, and can raise 403, before any `session_series`
  query executes, mirroring AUTH-03's own structural test and PGD-05's `/team/{member_id}/usage`
  precedent.
- **C-4 (soft-deleted-member edge case)** — Adopted as-is: a roster member with `removed_at`
  populated must still appear in historical `session_series` queries — the query filters only
  on `session_series` data, never on roster/`program_roster` status.

## Scope
- In: `GET /api/overview/program-detail/{program_id}/session-time-series` — range validation
  (7d/30d/90d, explicit 400), optional `member_id` filter, RBAC gating, zero-padded daily
  series, server-side `period_total_seconds`/`avg_seconds_per_day`, structured logging
  (`program_drilldown` on fetch, `member_view_denied` on gate denial).
- In: Next.js proxy route `/api/proxy/program-detail/{program_id}/session-time-series`
  (ADR-0008 pattern, matching PGD-01..04's existing proxies).
- Out: The chart UI and member-filter UI. No mockup shows either. `dashboards/Program
  Detail.html` (extracted per `docs/design/README.md`) contains exactly six sections —
  PROJECT SUMMARY, DAILY TOKEN CONSUMPTION, RELEASES VIA HARNESS, COMMANDS + TEAM, COMMANDS,
  TEAM — no session-time chart, no member filter; every `session`/`Member` string in that file
  belongs to PGD-05's shipped Project team table. The Engineering Manager Dashboard mockup adds
  only a MEMBER COMMAND POPUP, not this chart. The nearest analog in any of the six mockups is
  the Developer Dashboard's `MY SESSIONS TABLE` ("Your session-wise usage"), a per-session table
  scoped to the DEV epic, not a per-day PGD chart. The story's own Test-mapping names
  `SessionTimeChart.tsx` and `MemberFilter.tsx` as "unchanged components, FR-PD-15/16" — neither
  exists anywhere under `apps/web/src`. This is the same "story claims a component exists; it
  does not" finding PGD-04 § Scope documents; PGD-06 mirrors that precedent and ships the API
  only. Rendering is deferred to a follow-on story scoped against a design that actually shows
  this chart.
- Out: Writes to `session_series` (BED-01/BED-03 own that pipeline; this story is read-only).
- Out: Persona-scoped filtering beyond the two RBAC gates already named (`program_visibility`
  is open-aggregate by contract, A-004).

## Functional requirements

FRs trace 1:1 to story ACs; see `docs/stories/PGD-06.md` for canonical wording.
New impl constraints introduced below:

**PGD-06-FR-1** — Org/program-wide series is an aggregate, not a null-`member_id` read
*(corrects AC #1: `session_series` has no null-`member_id` rows — see Addressing Research
Conditions, C-1)*

The unfiltered view sums `session_time_seconds` across every member row for the program, per
day, for the resolved range. No query filters on `member_id IS NULL`; no such row is ever
produced by `_build_session_series`.

**PGD-06-FR-2** — Response shape: raw ints, matching the token-trend sibling
*(extends AC #4 with: exact field types and ownership)*

`points[].session_time_seconds`, `period_total_seconds`, `avg_seconds_per_day` are all raw
ints (seconds). Matching `/token-trend`'s precedent, not `/releases`'s pre-formatted-string
precedent — the frontend owns h/m display formatting (BED-02 api-conventions), the backend
never emits a formatted duration string.

**PGD-06-FR-3** — Unknown `program_id`: `200` with an all-zero series, no 404
*(extends AC #1/#6 with: existence-check behaviour)*

Matches the token-trend/commands/team sibling asymmetry (no 404), not the releases sibling
(404) — this route, like those three, is an activity aggregate with no `program_summary`
existence lookup. An unknown `program_id` returns `200` with a zero-padded all-zero series and
`period_total_seconds: 0`.

**PGD-06-FR-4** — Zero-padding to the fixed range length
*(extends AC #1/#2 with: exact padding rule, per story Decision log 2026-08-26)*

`points[]` always has exactly 7/30/90 entries for the resolved range; a day with no
`session_series` row (for the org aggregate) or no row for the filtered member gets
`session_time_seconds: 0`, never an omitted entry.

**PGD-06-FR-5** — `avg_seconds_per_day` divisor
*(extends AC #4 with: exact formula, matching token-trend precedent)*

`avg_seconds_per_day = period_total_seconds / <range's fixed day count>` (7, 30, or 90) — never
divided by the count of days that actually have data.

**PGD-06-FR-6** — Gate-before-query ordering for the member filter
*(extends AC #5 with: enforcement mechanism, matching PGD-05's `/team/{member_id}/usage`
precedent)*

When `member_id` is present and does not equal the requester's own id and the requester is not
`cio`, `member_in_program_visibility` MUST raise before `fetch_program_session_series` issues
any `session_series` query. No session-time data is fetched on the denied path.

## Non-functional requirements

- Performance: range/member-filter refresh ≤ 2s (NFR-002, sourced); initial Program Detail
  render ≤ 3s (NFR-001, sourced). Per `.claude/rules/performance-baseline.md`: single
  aggregate query per request, no N+1, range bounded to 7/30/90 days.
- Security: Per `.claude/rules/security-baseline.md`: applies to this new endpoint.
  `program_visibility` (open-aggregate) gates the unfiltered/self view; `member_in_program_visibility`
  (self OR cio) gates a non-self `member_id` filter (NFR-005, sourced). 401 for unauthenticated
  callers.
- Accessibility: N/A for this story's shipped surface — no new UI ships (see Scope). Per
  `.claude/rules/accessibility-baseline.md`: applies once a follow-on story renders the chart.
- Observability: structured JSON events `program_drilldown` on a successful fetch and
  `member_view_denied` on gate denial (NFR-011, sourced), matching PGD-03/04/05's
  `{method, path, program_id, range, status, latency_ms}` shape.

## Rollout plan
- **Strategy**: bang-bang — additive read-only endpoint on an existing router, no client
  currently depends on it (frontend deferred, see Scope).
- **Feature flag**: none.
- **Backout plan**: revert the router addition; no schema or migration to unwind (read-only).
- **Success signal**: endpoint returns correct zero-padded, differential-range series in
  production smoke traffic; no regression in PGD-01..05 latency on the shared `overview` router.

## Documentation requirements
- **README updates**: `README.md` API table — add a `GET
  /api/overview/program-detail/{program_id}/session-time-series` row alongside the existing
  `program-detail`/`token-trend`/`releases`/`commands`/`team` rows, documenting the raw-int
  shape, the no-404 empty behaviour, and the corrected "no null-`member_id` row" data-source
  note.
- **Runbook**: none.
- **API reference**: FastAPI `/docs` (auto-generated) covers the route; no separate reference
  needed.
- **Inline code comments**: `fetch_program_session_series()` docstring noting the org-wide
  view is a cross-member aggregate, not a null-`member_id` read (per C-1 correction).
- **Examples / how-to**: none.

## Open questions
None. Each shape question (route path, raw-ints, 404-vs-200, zero-padding, avg divisor, gate
choice) is settled above against a named sibling precedent, and the AC-1 correction is settled
by the verified absence of null-`member_id` rows.

Decisions logged in `docs/stories/PGD-06.md` § Decision log.

## Approvals
- **2026-09-17** — Pratik Pawar (PO + Designer + BA, single-approver mode): **APPROVE**
  - Recorded at the Product Gate (Phase 4), in the approver's own voice. Verdict collected
    interactively; drafting did not self-approve (a draft-time self-approval was written by
    `product-spec-agent` and removed by the orchestrator before the gate ran).
  - Feature Summary, FRs (PGD-06-FR-1..6), and User Flows reviewed; story AC-1..7 in scope.
  - UI specs: N/A — `design: n/a`. PGD-06 ships backend-only. No `DESIGN.md` is written: unlike
    PGD-04 (whose mockup panel existed and could be recorded as an API contract), no mockup shows
    this chart or its member filter at all, so there is no design to extract. See § Scope.
  - Edge Cases + Open Questions reviewed (0 open); test cases 17/17 automatable,
    coverage audit uncovered=[]
  - No-placeholder check ✓ · `[NEEDS CLARIFICATION]` count=0
  - Research verdict GO-WITH-CONDITIONS — all 4 conditions addressed above; C-1 **corrected**
    (the assumed `(program_id, member_id, date)` index does not exist), C-2 moot under
    backend-only scope.
  - Approved knowing AC-1's original premise is factually wrong against the shipped schema:
    `session_series` carries no null-`member_id` rows, so PGD-06-FR-1 specifies a cross-member
    SUM instead. Chart/filter rendering stays unbuilt until a story is scoped against a design
    that shows it.
  - Coverage-audit `org_id` note resolved pre-gate: `_ORG_ID = "org-1"` is a hardcoded
    single-org singleton (`services/api/app/services/rollup_rebuild.py:118`, D-03) — no
    multi-tenancy, so no cross-org FR/AC or test was added.
  - Tracker subtasks: #448 (research), #449 (plan-requirements)
