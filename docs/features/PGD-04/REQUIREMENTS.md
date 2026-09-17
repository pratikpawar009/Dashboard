# Feature: PGD-04 — Program command activity

## Problem
A signed-in user viewing a program's detail page cannot see which Harness commands the
program runs most, or how that mix shifts across time windows. The "Commands executed"
panel on the Program Detail mockup has no backing data.

## Outcome
`GET /api/overview/program-detail/{program_id}/commands?range=` returns each distinct
command run in the selected range with its count, ordered descending, plus a total —
enabling the mockup's panel to render once a consumer exists (see Scope).

## Constraints
- Must reuse the `overview` router (`services/api/app/api/overview.py`, `prefix="/api/overview"`)
  — a new router is out of scope.
- Must read `usage_events`, never `program_commands` (the latter is lifetime-only; see
  Addressing Research Conditions #4).
- Must reuse `CommandsPanel`/`CommandEntry` from `app/schemas/personal_usage.py` — no new
  schema module.
- NFR-002 perf budget (≤2s range refresh) inherited from PGD-02/03 precedent.

## Solution sketch
Add a fourth sibling endpoint to the `overview` router, following PGD-02/03's exact shape:
`program_visibility()` gate → `_range_with_default()` → a new `fetch_program_commands()`
service function that aggregates `usage_events` by `command` for the given `program_id` and
range window (mirroring SHP-02's `_fetch_command_rows`, `program_id` swapped for `user`),
orders descending by count, computes `barStyle` via the max-of-range formula, and returns
the existing `CommandsPanel` envelope. No new tables, no new schemas, no new router.

## Addressing Research Conditions
- **C-1 (path)**: Settled — `GET /api/overview/program-detail/{program_id}/commands` on the
  existing `overview` router; browser-facing proxy `/api/proxy/program-detail/{program_id}/commands`
  (ADR-0008). Story AC-1 and decision log already corrected 2026-09-17; FR below carries no
  further path work.
- **C-2 (empty-program behaviour)**: Settled — unknown `program_id` returns `200
  {total_runs: "0", items: []}`. No `program_summary` existence lookup, no 404 path. See
  PGD-04-FR-1.
- **C-3 (schema ownership)**: Settled — import `CommandsPanel` + `CommandEntry` from
  `app/schemas/personal_usage.py`; no `schemas/program_commands.py` is created. A co-consumer
  note is added to `personal_usage.py`'s module docstring; a shared `schemas/commands.py` is
  carried forward only if a third consumer appears.
- **C-4 (data source)**: Settled, critical — aggregate from `usage_events` (per-event `ts`),
  never `program_commands` (lifetime-only rollup, no time filter — confirmed at
  `rollup_rebuild.py:246`). Mirrors SHP-02's `_fetch_command_rows` with `WHERE "user"=:user_id`
  swapped for `WHERE program_id=:program_id`, using the existing
  `ix_usage_events_program_id_command` index. Mitigation is a mandatory differential-range
  acceptance criterion (PGD-04-FR-2): a `7d` and a `90d` request against the same seeded
  multi-window data MUST return different `total_runs`/counts — a suite that only asserts
  `200` + non-empty cannot catch a silent regression back to the lifetime table.
- **C-5 (frontend scope)**: Settled — PGD-04 ships **backend-only**. See Scope below for basis.

## Scope
- In: `GET /api/overview/program-detail/{program_id}/commands` endpoint — range validation,
  RBAC gate, `usage_events` aggregation, `CommandsPanel` response, structured logging.
- In: Next.js proxy route `/api/proxy/program-detail/{program_id}/commands` (ADR-0008 pattern,
  matching PGD-01/02/03's existing proxies).
- Out: Rendering the "Commands executed" panel in the browser. The story's own Test-mapping
  states this is "a backend-only story," but its supporting claim — that
  `frontend/.../CommandsActivity.tsx` "is unchanged and already consumes this shape" — is
  verified false: no commands component exists anywhere under `apps/web/src`, and no other
  RTM story (checked ARC-01, DEV-01, PMD-01, EMD-01, PGD-05/06/07) claims ownership of it
  either. Building an unrequested, unspecified frontend component would violate CLAUDE.md
  § Design system ("if a story seems to need something the mockups do not show, stop and
  raise it — do not design it") in the opposite direction: the mockup *does* show the panel,
  but no story's AC asks this one to render it, and inventing frontend scope not in this
  story's ACs is equally out of bounds. PGD-04 therefore ships the API only; the mockup's
  Commands panel stays unrendered until a follow-on story explicitly scopes
  `CommandsActivity.tsx` against this contract.
- Out: `program_commands` table changes (BED-01 owns writes via `rollup_rebuild`; this story
  is read-only and does not touch it).
- Out: Persona-scoped filtering (the `program_visibility` gate is open-aggregate by contract,
  A-004).

## Functional requirements

FRs trace 1:1 to story ACs; see `docs/stories/PGD-04.md` for canonical wording.
New impl constraints introduced below:

**PGD-04-FR-1** — Empty/unknown program_id response  *(extends AC #1 with: no existence check)*

For any `program_id` — known, quiet (no in-range activity), or entirely unknown — the handler
performs no `program_summary` lookup and never returns 404. It returns `200
{total_runs: "0", items: []}` whenever the `usage_events` aggregation yields no rows for the
selected range.

**PGD-04-FR-2** — Differential-range aggregation source  *(extends AC #1 with: data source + required test)*

The service MUST read `usage_events` (per-event `ts`), filtered by `program_id` and the
resolved range window, never `program_commands`. Acceptance requires a test asserting a `7d`
request and a `90d` request against the same seeded multi-window fixture return different
`total_runs` values — a test that only checks `200` + non-empty response does not satisfy
this FR.

**PGD-04-FR-3** — Bar style formula  *(extends AC #3 with: exact formula, resolves AC-3 prose ambiguity)*

`barStyle` per command is computed as `round(count / MAX(counts in this range and program) * 100)%`
— max-of-range, not share-of-total. AC-3's prose ("proportional bar... relative to the highest-run
command") already implies this; ADR-0009 is the authority per CLAUDE.md § Design system, and this
FR exists only because a literal reading of "total" elsewhere in the codebase (e.g.
`total_run_count`) could mislead an implementer into share-of-total.

## Non-functional requirements

- Performance: range/filter refresh ≤ 2s (NFR-002, sourced from story). No N+1: single
  `usage_events` aggregate query per request, per `.claude/rules/performance-baseline.md`.
- Security: Per `.claude/rules/security-baseline.md`: applies to this new endpoint. RBAC via
  `rbac-checks.program_visibility` — open-aggregate, any authenticated session, never
  persona- or membership-gated (NFR-005, sourced). 401 for unauthenticated callers.
- Accessibility: N/A for this story's shipped surface — no new UI ships (see Scope). Per
  `.claude/rules/accessibility-baseline.md`: applies once a future story renders the panel.
- Observability: Per `.claude/rules/performance-baseline.md` (cache/logging discipline):
  structured request log (method, path, program_id, range, status, latency) via `structlog`,
  matching PGD-03's `program_releases_fetched` pattern. No dedicated audit event for the
  open-aggregate `program_visibility` check (NFR-011, sourced — consistent with PGD-01/02/03).

## Screen inventory

No screen ships in this story (see Scope: backend-only). The mockup's "Commands executed"
section on Program Detail (`docs/design/mockups/Program Detail.html`, `<!-- COMMANDS -->`)
is the eventual consumer of this endpoint's contract, deferred to a follow-on frontend story.

| Screen | Route | Render | Primary purpose | States | Story ACs covered |
|---|---|---|---|---|---|
| N/A — no UI ships under PGD-04 | — | — | — | — | — |

## Visual spec

See [DESIGN.md](./DESIGN.md) — the mockup's "Commands executed" panel documented as the binding contract this backend-only API must satisfy (fields consumed, pre-formatted values, max-of-range bar formula, undesigned empty state); rendering deferred to a follow-on frontend story.

## Rollout plan
- **Strategy**: bang-bang — additive read-only endpoint on an existing router, no client
  currently depends on it (see Scope: frontend deferred).
- **Feature flag**: none.
- **Backout plan**: revert the router addition; no schema or migration to unwind.
- **Success signal**: endpoint returns correct differential-range totals in production
  smoke traffic (PGD-04-FR-2's test passing is the pre-ship gate); no regression in
  PGD-01/02/03 latency on the shared `overview` router.

## Documentation requirements
- **README updates**: `README.md` API table — add a `GET
  /api/overview/program-detail/{program_id}/commands` row alongside the existing
  `program-detail`/`token-trend`/`releases` rows, documenting the no-404 empty behavior and
  the `usage_events`-not-`program_commands` data source.
- **Runbook**: none.
- **API reference**: FastAPI `/docs` (auto-generated) covers the route; no separate reference
  needed.
- **Inline code comments**: `fetch_program_commands()` service function — docstring noting
  the `usage_events` source (not `program_commands`) per C-4, mirroring SHP-02's
  `_fetch_command_rows` docstring style.
- **Examples / how-to**: none.

## Open questions
None. C-5 (frontend scope) is settled in Scope above with basis, not left as a marker per the
research condition's own instruction that a mockup+RTM-derivable answer must not become a
silent assumption or a marker — the evidence (no component exists, no story claims it) is
conclusive.

Decisions logged in `docs/stories/PGD-04.md` § Decision log.

## Approvals
- **2026-09-17** — Pratik Pawar (PO + Designer + BA, single-approver mode): **APPROVE**
  - Recorded at the Product Gate (Phase 4), in the approver's own voice. Verdict collected
    interactively; drafting did not self-approve.
  - Feature Summary, FRs, User Flows reviewed
  - UI specs: `docs/features/PGD-04/DESIGN.md` is complete — it documents the Program Detail
    mockup's "Commands executed" panel as the binding API contract. No UI ships in PGD-04;
    rendering is deferred to a follow-on story.
  - Edge Cases + Open Questions reviewed (0 open); test cases 17/17 automatable, coverage audit uncovered=[]
  - No-placeholder check ✓ · `[NEEDS CLARIFICATION]` count=0
  - Research verdict GO-WITH-CONDITIONS — all 5 conditions addressed above
  - Tracker subtasks: #421 (research), #422 (plan-requirements)
