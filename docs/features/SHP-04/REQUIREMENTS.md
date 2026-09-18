# Feature: SHP-04 — Artifacts generated panel

## Problem

An architect, product-manager, or developer viewing a program's dashboard has no visibility into
what the program has actually produced — how many PRDs, user stories, test cases, architecture
diagrams, and API specs it has generated. `program_artifacts` holds this data (live for
`program_id='dashboard'`: `prd=4, user_story=45, test_case=274, arch_diagram=0, api_spec=0`) but no
route exposes it, and no UI renders it.

## Outcome

An authorized persona (architect, product-manager, developer) viewing a program sees an "Artifacts
generated" panel listing all 5 canonical artifact types with their counts, including types with
zero production. A `cio` or `engineering-manager` session gets `403` with no data body. A program
with no `program_artifacts` rows yet still renders all 5 types at `0`, never an error.

## Constraints

- Design contract is the identical "Artifacts generated" panel appearing on the Architect,
  Developer, and Product Manager dashboard mockups (`docs/design/mockups/{Architect,Developer,
  Product Manager} Dashboard.html`) — research confirmed byte-identical markup and bindings across
  all three; this is one screen with a swapped persona label, not three designs.
- Values arrive pre-formatted per `docs/design/README.md`, except `count`, which is a raw int per
  ADR-0009's magnitude-formatting split (same split OVW-04/PGD-01 already apply).
- The mockup binds `a.bg`/`a.color` on the wire (`docs/design/README.md` § "templates also bind
  presentation") — per the PO's binding decision (`docs/research/SHP-04.md` § Resolved questions
  #1), these ship as server-owned presentation constants, not client-derived styling, following
  ADR-0009's precedent for `personal-usage-api` cards and ADR-0007's for `program-detail-api`'s
  `summary`.
- `governance_visibility` (`services/api/app/core/rbac.py:196-243`) is shipped and unit-tested but
  has zero route consumers today — SHP-04 is its first live caller.
- No frontend `ArtifactsPanel.tsx` component exists in `apps/web/src` — the story's NFR claiming
  reuse of an "existing" component is incorrect; the component must be built new (see Scope, Open
  questions).

## Solution sketch

Add `GET /api/artifacts/{program_id}` to a new `app/api/artifacts.py` router, gated by
`governance_visibility(current_user, program_id)` (architect | product-manager | developer only;
cio/engineering-manager denied). A new `fetch_program_artifacts()` service function queries
`program_artifacts` for the given `program_id`, fills in a `count: 0` row for any of the 5
canonical types with no row, and maps each to its server-owned `tag`/`name`/`bg`/`color`
presentation constants in the mockup's fixed order. On the frontend, build a new `ArtifactsPanel`
component consumed identically by the Architect, Developer, and Product Manager dashboard pages.

## Addressing Research Conditions

- **C-1 (response JSON shape)**: resolved with the PO 2026-09-18 — `{items: [{tag, name, count,
  bg, color}]}`, exactly 5 rows, mockup order is the contract. Mitigation: **SHP-04-FR-1** below
  pins the exact wire shape, field-by-field, sourced against the decoded mockup's `sc-for`
  bindings (`{{ a.tag }}`, `{{ a.name }}`, `{{ a.count }}`, `{{ a.bg }}`, `{{ a.color }}`) and
  ADR-0009's server-owned-constants precedent.
- **C-2 (governance-denial logging event)**: resolved with the PO 2026-09-18 — no separate
  `governance_view_denied` event; `governance_visibility` already emits
  `rbac_check_governance_visibility` with an `outcome` field and raises the 403 itself, before any
  data read. Mitigation: **SHP-04-FR-2** below states this explicitly and supersedes the story's
  Decision-log entry naming `governance_view_denied` — the route adds no additional logging around
  the gate call, matching the precedent in `personal_usage.py`/`overview.py`.

## Scope

- In:
  - `GET /api/artifacts/{program_id}` route + response schema on a new `app/api/artifacts.py`.
  - `fetch_program_artifacts()` service: query `program_artifacts` by `program_id`, zero-fill the 5
    canonical types, map to the mockup's fixed presentation constants.
  - `governance_visibility` gate wired as the route's first dependency (its first live consumer).
  - Empty-program `200` with all 5 types at `count: 0` (AC-3).
  - New frontend `ArtifactsPanel` component, consumed by the Architect, Developer, and Product
    Manager dashboard pages (byte-identical rendering per the mockup).
- Out:
  - Reconciling `program_artifacts`' `user_story=45` against `program_summary.features=0`
    (`OVW-04`'s program board reads a different table for a related but distinct metric) — this is
    a pre-existing two-table inconsistency, not something SHP-04 resolves.
  - Any write/ingest path into `program_artifacts` — owned by `ING-03`'s
    `POST /api/ingest/artifacts`, already shipped.
  - CIO- or engineering-manager-facing artifact views — explicitly denied by AC-2; no alternate
    surface for those personas is in scope here.
  - Dashboard composition beyond this one panel (layout, other panels on ARC-01/DEV-01/PMD-01) —
    deferred to those stories, which consume this contract.

## Functional requirements

FRs trace 1:1 to story ACs; see `docs/stories/SHP-04.md` for canonical wording.
New impl constraints introduced below:

**SHP-04-FR-1** — Response shape: 5-row fixed-order list, server-owned presentation constants
*(extends AC-1, AC-3, AC-4 with: concrete wire shape)*

`GET /api/artifacts/{program_id}` returns:

```
{
  "items": [
    {"tag": "PRD", "name": "Product Requirement Docs", "count": int, "bg": "#e9f1fd", "color": "#2a6fdb"},
    {"tag": "US",  "name": "User stories",            "count": int, "bg": "#f0edfb", "color": "#6a4fd0"},
    {"tag": "TC",  "name": "Test cases",              "count": int, "bg": "#eaf6ef", "color": "#1f8a5b"},
    {"tag": "AD",  "name": "Architecture diagrams",   "count": int, "bg": "#fdefe9", "color": "#d97757"},
    {"tag": "API", "name": "API specifications",      "count": int, "bg": "#fef4e6", "color": "#c08a1e"}
  ]
}
```

`items` is always exactly 5 entries in this fixed order — the canonical type order in
`services/api/app/schemas/ingest_artifacts.py::_CANONICAL_ARTIFACT_TYPES` (`prd`, `user_story`,
`test_case`, `arch_diagram`, `api_spec`) — regardless of how many types have a `program_artifacts`
row for this `program_id`; a missing row yields `count: 0` (AC-3), never an omitted entry. `tag`,
`name`, `bg`, `color` are server-owned presentation constants (one fixed pair per canonical type,
analogous to `docs/design/tokens.md` § Program type colors) — never derived client-side, per the
PO's binding decision. `count` is a raw int, mirroring `program-detail-api`'s `summary.value` /
`program-board-api`'s `metrics[].value` split precedent for magnitude fields the frontend does not
need to reformat (a bare integer 0–9999 needs no M/K suffixing). **The five constant pairs are RESOLVED from the design source** (Phase-2 extraction, recorded in
`DESIGN.md`): the sample data is a flat literal array in the mockups' embedded `<script>` at decode
L899-905, byte-identical across the Architect, Developer and Product Manager pages, and its order
matches `_CANONICAL_ARTIFACT_TYPES` position-for-position. The values are inlined in the block
above. Four of the five colour pairs are `docs/design/tokens.md` § Persona colors reused verbatim
as a categorical palette with no semantic link (`US` purple does not mean "the architect's
artifact"); only `API`'s `#fef4e6` tint is new to the token set.

**SHP-04-FR-2** — Governance-denial logging: no route-level event *(extends AC-2 with: logging
contract, supersedes story Decision log)*

The route adds zero logging of its own around the `governance_visibility` dependency call.
`governance_visibility` (`services/api/app/core/rbac.py:196-243`) logs
`rbac_check_governance_visibility` with `outcome="denied"` and raises `HTTPException(403)` itself,
before the route reads any `program_artifacts` row — matching the no-additional-logging pattern in
`personal_usage.py`/`overview.py`. The story's Decision-log entry naming a separate
`governance_view_denied` event is superseded by this resolution (`docs/research/SHP-04.md` §
Resolved questions #2) and must not be implemented.

**SHP-04-FR-3** — `program_id` is not membership-scoped by this gate *(extends AC-1 with: gate
cascade behaviour)*

`governance_visibility(current_user, program_id)` runs the persona check FIRST; only when it
passes AND `program_id is not None` does it cascade into `program_visibility` (open-aggregate: any
authenticated session, no per-program `WHERE program_id IN current_user.programs` filter — same
posture as `/api/overview/program-detail/{program_id}` and its siblings, README.md § API). An
unknown `program_id` therefore is not rejected by the gate; the service layer's zero-row case
(AC-3) is what actually produces the all-zero response for a nonexistent or artifact-less program
— there is no dedicated 404 path for this endpoint.

## Non-functional requirements

- Performance: panel render ≤ 3s under normal load (NFR-001, sourced from story). Query is a
  single indexed lookup (`program_artifacts` unique on `[program_id, type]`) over at most 5 rows —
  no pagination needed (fixed 5-row response, closed vocabulary).
- Security: Per `.claude/rules/security-baseline.md`: applies to the new `GET
  /api/artifacts/{program_id}` endpoint. `governance_visibility` (architect | product-manager |
  developer only) enforced server-side, never UI-only hiding. This is the gate's first live route
  consumer — unit-tested in isolation only until now; route-level tests must cover authorized
  (architect/product-manager/developer), denied (cio/engineering-manager), and
  persona-resolution-failure paths explicitly, since no existing route exercises this gate's
  behaviour under real request/response conditions.
- Accessibility: Per `.claude/rules/accessibility-baseline.md`: applies to the new
  `ArtifactsPanel` UI on the Architect, Developer, and Product Manager dashboards. Each row's
  `bg`/`color` presentation pair is paired with the `tag`/`name` text labels already in the
  markup — color is never the sole indicator of artifact type.
- Observability: no new logging beyond `rbac_check_governance_visibility` (SHP-04-FR-2); this
  endpoint introduces no additional structured event.

## Screen inventory

Scoped to the "Artifacts generated" panel — byte-identical across the Architect, Developer, and
Product Manager dashboard mockups (`docs/design/mockups/{Architect,Developer,Product Manager}
Dashboard.html`); treated as one screen per `docs/design/README.md` § Screen inventory, not three.

| Screen | Route | Render | Primary purpose | States | Story ACs covered |
|---|---|---|---|---|---|
| Artifacts generated panel | — (embedded panel on `/architect`, `/developer`, `/product-manager` dashboard routes — ARC-01/DEV-01/PMD-01) | server (initial load, composed into the parent dashboard page) | List the program's 5 canonical artifact types with counts | Populated / Loading (5 skeleton rows per `hint-placeholder-count="5"`) / Empty (all zero counts, AC-3) / Error (403 non-authorized persona, AC-2) | AC-1, AC-2, AC-3, AC-4 |

## Visual spec

See [DESIGN.md](./DESIGN.md) — the in-scope mockup region (`ARTIFACTS`), its exact bindings, literal copy, row anatomy, the five resolved tag/name/bg/color constants, states and form factors. Hand-authored during Phase 2: `ux-agent` is not installed in this repo, the same gap SHP-01, PGD-01, OVW-01, OVW-05 and OVW-04 recorded.

## Rollout plan

- **Strategy**: bang-bang — new route handler, new frontend component, no existing behaviour
  changed, additive only. Per `.claude/rules/reusability-baseline.md`, no config-switch forks the
  call graph.
- **Feature flag**: none.
- **Backout plan**: remove the `GET /api/artifacts/{program_id}` route from `artifacts.py` and the
  `ArtifactsPanel` section from the three consuming dashboard pages; no other route or panel is
  affected.
- **Success signal**: an authorized session's `GET /api/artifacts/{program_id}` returns 200 with
  all 5 types in mockup order within the 3s panel-render budget; a denied session gets 403 with no
  data body; verified in staging before ARC-01/DEV-01/PMD-01 compose against it.

## Documentation requirements

- **README updates**: `README.md` API table — add a `GET /api/artifacts/{program_id}` row (request,
  response shape, 403 case, empty-program zero-fill case), matching the existing
  `/api/overview/program-detail/*` row format.
- **Runbook**: none.
- **API reference**: FastAPI's generated `/docs` (OpenAPI); the new response schema documents
  itself, no separate file.
- **Inline code comments**: `app/api/artifacts.py` — the route's docstring must note (a) the
  zero-fill contract for missing canonical types (AC-3), and (b) that `governance_visibility` is
  this gate's first live route consumer, so a future edit doesn't silently break the only place
  exercising it end-to-end.
- **Examples / how-to**: none.

## Open questions

None — both items raised during drafting were settled before the Product Gate. See
§ Resolved questions.

## Resolved questions

| # | Question | Resolution |
|---|---|---|
| 1 | Exact tag abbreviation + hex `bg`/`color` pair per canonical artifact type | **Resolved from the design source, not invented.** The five pairs are a literal array in the mockups' embedded script (decode L899-905), byte-identical across the Architect, Developer and Product Manager pages, ordered position-for-position with `_CANONICAL_ARTIFACT_TYPES`. Inlined in SHP-04-FR-1, specified in `DESIGN.md` |
| 2 | The story references an "existing" `ArtifactsPanel.tsx` | **No such component exists** in `apps/web/src` — verified. This PRD's § Scope treats the panel as new work, not reuse, so nothing in the plan depends on the claim. Carry-forward: the story's NFR wording should be corrected at its next edit (not reopened for this) |

Decisions logged in `docs/stories/SHP-04.md` § Decision log.

## Approvals

- **2026-09-18** — Pratik Pawar (PO + Designer + BA, single-approver mode covers all): **APPROVE**
  - Feature Summary, FRs, User Flows reviewed
  - UI specs pending in `DESIGN.md` (ux-agent, Phase 2) — Screen inventory above is authoritative
    input for that step
  - Edge Cases, Open Questions, test-case completeness reviewed
  - No-placeholder check ✓ · `[NEEDS CLARIFICATION]` count=0 (the one marker was resolved from the design source in Phase 2)
  - Research verdict GO-WITH-CONDITIONS (both conditions addressed in § Addressing Research
    Conditions)
  - Tracker subtask: pratikpawar009/Dashboard#486 (research). PRD subtask is filed by
    `/arh-plan-requirements` Phase 3 (`tracker_prd`), not yet run at this Phase 1 checkpoint.

- **2026-09-18** — Pratik Pawar (PO + Designer + BA, single-approver mode): **APPROVE** (Product Gate)
  - 3 FRs / 4 NFRs reviewed; 11 test cases, `coverage_audit.uncovered == []`; pre-push secret scan clean.
  - Both research conditions satisfied before the gate (response shape per ADR-0009; no separate
    `governance_view_denied` event — the gate's own logging stands).
  - The single `[NEEDS CLARIFICATION]` was resolved from the design source during Phase 2 — the five
    tag/colour constants are a literal array in the mockups' embedded script, identical across the
    Architect, Developer and Product Manager pages. Not invented.
  - FR-1's `name` strings corrected to the mockup's actual copy (`Product Requirement Docs`,
    `Architecture diagrams`, `API specifications`) before approval.
  - Accepted as carry-forward, not blockers: tag-chip contrast below WCAG AA (systemic to the
    design system's tint-on-tint recipe, mitigated by the adjacent full-contrast label), and the
    story's reference to a non-existent `ArtifactsPanel.tsx` (scoped as new work).
  - Tracker: story #32 · research #486 · plan-requirements #487.

