# Feature: PGD-03 — Releases list (paginated)

## Problem
Program Detail shows AI-tooling usage but no delivery output. A signed-in user cannot see what actually shipped for a program alongside its token spend, so investment and output stay disconnected on the one screen meant to correlate them.

## Outcome
Program Detail renders a range-filterable, paginated releases panel (`GET /api/overview/program-detail/{program_id}/releases`) whose rows match the shipped mockup exactly, scrolls without breaking layout, and returns a byte-identical response for any authenticated persona.

## Constraints
- Router: subroute on the existing `overview` router (`app/api/overview.py`), alongside PGD-01/PGD-02 — not a standalone `/api/program-detail/...` route.
- Reuse `validate_range` (`app/dependencies/range.py`) and `program_visibility` (`app/core/rbac.py`) unchanged.
- Response shape is fixed by `dashboards/Program Detail.html` bindings, not by `program_releases` column names.
- NFR-002: range/filter refresh ≤ 2s (sourced, story NFR).

## Solution sketch
Add `GET /api/overview/program-detail/{program_id}/releases` returning paginated, range-scoped rows from `program_releases`, pre-formatted server-side into the mockup's field names and its 3-entry release-kind vocabulary. The frontend mounts a `ReleasesList` panel on the existing Program Detail page with its own independent range switcher and a fixed-height scroll container.

## Addressing Research Conditions
- C-1: Route prefix — DECIDED. Endpoint registered as `GET /api/overview/program-detail/{program_id}/releases`, subroute on the existing `overview` router. This PRD's FR-PGD03-1 records the path; downstream plan/implementation update `docs/stories/PGD-03.md` AC-1 + Test mapping and the README API table to match (tracked as a plan task, not re-litigated here).
- C-2: Wire contract follows the mockup. § Functional requirements FR-PGD03-2 and FR-PGD03-3 fix the exact response shape (`ver`, `label`, `dot`, `tagColor`, `tagBg`, `date`, `stories`, `prs`, `relTotal`) and the corrected 3-entry status vocabulary, superseding the story's `major|minor|patch` Decision-log entry.
- C-3: Index coverage. FR-PGD03-4 requires confirming a `program_releases(program_id, date)` index exists (BED-01 migration 001 or later) before implementation claims the NFR-002 ≤2s budget is met; if absent, plan-implementation adds a migration as a task rather than leaving the budget unevidenced.

## Scope
- In: `GET /api/overview/program-detail/{program_id}/releases` endpoint; `ReleasesList` panel on Program Detail; range switcher (7d/30d/90d, independent of PGD-02's); pagination (offset/limit, limit clamped to 50); RBAC via `program_visibility`; 6-row placeholder empty/loading state; scroll container per mockup.
- Out: editing/creating releases; release detail drill-down; changing `program_releases` schema; ARC-01/DEV-01/PMD-01/EMD-01 consumption of this endpoint (their own stories).

## Functional requirements

FRs trace 1:1 to story ACs; see `docs/stories/PGD-03.md` for canonical wording. New impl constraints introduced below:

**PGD-03-FR-1** — Route path *(extends AC #1 with: exact path)*

`GET /api/overview/program-detail/{program_id}/releases`, registered on the existing `overview` `APIRouter` (`app/api/overview.py`), matching PGD-01/PGD-02 prefix.

**PGD-03-FR-2** — Response row shape *(extends AC #1 with: mockup wire contract, not BED-01 column names)*

Each row: `{ver, label, dot, tagColor, tagBg, date, stories, prs}`. Mapping from `program_releases`: `version`→`ver`; `story_count`→`stories` (string); `pr_count`→`prs` (string); `date`→pre-formatted `"Jul 15"` (no year). `tagColor`/`tagBg` are the program's theme colours, hoisted to response top level (`ProgramReleasesResponse.tag_color` / `.tag_bg`) rather than repeated per row — they are program-level, not per-release, per research § Design Validation; the frontend applies them to every row's tag.

**PGD-03-FR-3** — Status indicator vocabulary *(extends AC #1 with: corrected status mapping, supersedes story Decision log)*

`label` + `dot` derived from `program_releases.type` via a fixed, closed 3-entry map: `Feature release` (`#1f8a5b`), `Patch release` (`#2a6fdb`), `Hotfix` (`#d1495b`). This corrects the story's Decision-log `major|minor|patch` assumption, which contradicts the mockup. A `type` value outside this set is a data-integrity error, not a rendering case — the service raises rather than emitting an unstyled row.

**PGD-03-FR-4** — Range-scoped total field name *(extends AC #1 with: field name)*

Total row count for the active range window ships as `relTotal` (string), not `total_count` — matches the mockup binding `{{ relTotal }}`; distinct from PGD-01's program-lifetime "Releases done via Harness" summary-strip count.

**PGD-03-FR-5** — Pagination clamping *(extends AC #2 with: reuse target and a default-value conflict to resolve)*

`limit` > 50 is clamped to 50, never rejected. Reuse BED-02's shipped `get_offset_limit` dependency (`app/dependencies/pagination.py`), which already implements `min(limit, MAX_OFFSET_LIMIT)` with `ge=`-only bounds precisely because `Query(..., le=N)` raises 422 instead of clamping (BED-02 D-01). Do **not** copy `app/api/activities.py`'s `le=MAX_PAGE_SIZE` pattern — that one rejects, which is the opposite of the required behaviour.

Conflict to resolve in plan-implementation: `get_offset_limit` defaults `limit` to `MAX_OFFSET_LIMIT` (50), but story AC-1 specifies a default of **20**. Either parameterise the shared dependency's default or declare PGD-03's own `limit` default explicitly at the route; the shared clamp must not be forked. Whichever is chosen, an omitted `limit` yields 20 for this endpoint.

**PGD-03-FR-6** — `total_count`/`relTotal` window parity *(extends AC #1/#2 with: implementation guardrail)*

The count query and the paginated row query MUST share the identical `date` window predicate — no unbounded count while rows are bounded. Covered by a dedicated test per range value (7d/30d/90d).

**PGD-03-FR-7** — Index coverage precondition *(extends NFR-002 with: verification gate)*

Before claiming the ≤2s budget met, confirm `program_releases(program_id, date)` has covering index support (BED-01 migration 001+). If absent, plan-implementation adds a migration; do not defer silently.

## Non-functional requirements
- Performance: range/filter refresh ≤ 2s (NFR-002, sourced); contingent on FR-PGD03-7 index confirmation.
- Security: Per `.claude/rules/security-baseline.md`: applies to this new endpoint. RBAC via `program_visibility` (open-aggregate, any authenticated session; byte-identical cross-persona response, no per-program gating) — never UI-only hiding.
- Accessibility: Per `.claude/rules/accessibility-baseline.md`: applies to the `ReleasesList` panel and its range switcher (keyboard-operable, WCAG AA).
- Observability: structured request log (method, path, program_id, range, offset, limit, status, latency) via `structlog`; `program_visibility` has no dedicated audit event by design (open-aggregate check).

## Screen inventory

| Screen | Route | Render | Primary purpose | States | Story ACs covered |
|---|---|---|---|---|---|
| Releases panel (Program Detail) | /program/:program_id (embedded panel, no own route) | server (initial fetch) + client (range switch, pagination) | Show range-filtered, paginated release history for a program | Populated / Loading (6-row placeholder) / Empty (0 releases in range) / Error | AC #1–#7 |

## Visual spec

See [DESIGN.md](./DESIGN.md) — panel layout, grid, bindings, release-kind colours, and pre-formatted value rules extracted from the authored `html-mockup` source.

## Rollout plan
- **Strategy**: bang-bang
- **Feature flag**: none — additive endpoint + new panel, no existing behavior changed
- **Backout plan**: revert the router addition and remove the panel from the Program Detail page; no schema or migration to unwind (unless FR-PGD03-7 adds an index migration, in which case backout leaves the index in place — additive, harmless)
- **Success signal**: p95 endpoint latency < 2s sustained under representative data (5000+ releases/program) in validation phase

## Documentation requirements
- **README updates**: `README.md` API table — add `GET /api/overview/program-detail/{program_id}/releases` row (path, request, response), correcting the story's `/api/program-detail/...` wording per C-1.
- **Runbook**: none
- **API reference**: FastAPI `/docs` (auto-generated from the new route + Pydantic schemas)
- **Inline code comments**: `app/schemas/program_releases.py` — docstring noting the mockup-driven field mapping (ver/stories/prs/relTotal) so a future reader doesn't "fix" it back to BED-01 column names
- **Examples / how-to**: none

## Open questions

None open.

The release-kind vocabulary has **exactly 3 distinct entries** — `Feature release` (dot `#1f8a5b`), `Patch release` (dot `#2a6fdb`), `Hotfix` (dot `#d1495b`). The mockup's `genReleases` `kinds` array holds 4 elements, but `Feature release` is listed twice to weight it 2-in-4 in the random picker; that duplication is sample-data generation, not a fourth kind. `hint-placeholder-count="6"` on the row list is the six-row loading placeholder and is unrelated to the kind vocabulary (the separate `hint-placeholder-count="3"` on the range switcher corresponds to 7d/30d/90d).

Decisions logged in `docs/stories/PGD-03.md` § Decision log.

## Approvals

| Role | Reviewer | Date | Verdict |
|---|---|---|---|
| Product Owner | Pratik Pawar | 2026-09-16 | APPROVE |
| Design (html-mockup) | Pratik Pawar | 2026-09-16 | APPROVE — mockup is the authored source; DESIGN.md records the extracted contract |
| BA | Pratik Pawar | 2026-09-16 | APPROVE — edge cases and test-case feasibility confirmed (22 cases, 19 automatable, 3 e2e deferred pending a runner) |

Gate: **APPROVE** (2026-09-16). Recorded via `/arh-plan-requirements` Phase 4.
