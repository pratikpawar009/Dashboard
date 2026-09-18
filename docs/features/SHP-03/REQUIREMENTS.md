# Feature: SHP-03 — Personal session-wise usage list (paginated)

## Problem

An individual-contributor persona (architect, developer, product-manager) viewing their own
dashboard sees usage cards, a daily-token chart, and a commands breakdown (SHP-02), but no
session-level detail — no way to see *which* sessions produced that usage, when, for how long, or
how many tokens each consumed. `GET /api/personal-usage/{user_id}` does not return this; no route
exposes `user_sessions` rows today.

## Outcome

An individual-contributor persona's own dashboard renders a paginated "Your session-wise usage"
table — one row per session (name, identifier + date, duration, tokens), most-recent-first,
20 rows per page — backed by a new `GET /api/personal-usage/{user_id}/sessions` route. A
cross-user request from a non-`cio` persona is denied with `403` and no data body. A user with
zero sessions sees an empty table, not an error.

## Constraints

- Design contract is the "MY SESSIONS TABLE" section (mockup comment) on the Architect, Developer,
  and Product Manager dashboard mockups (`docs/design/mockups/{Architect,Developer,Product
  Manager} Dashboard.html`) — byte-identical bindings across all three (verified: same `sc-for`
  block, same field names `s.title`/`s.meta`/`s.duration`/`s.tokens`, same
  `hint-placeholder-count="20"`). One screen, not three, matching the SHP-04 precedent
  (`docs/features/SHP-04/REQUIREMENTS.md` § Constraints).
- SHP has no entry in `docs/design/schema.json`'s `designSystem.pages.features` map — this story's
  design contract is scoped by mapping to the ARC/DEV/PMD mockup files directly, the same
  resolution SHP-04 used for its own "Artifacts generated" panel.
- The mockup row anatomy is **3 bound fields, not 4**: `{{ s.title }}` (name), `{{ s.meta }}` (a
  single composite string — decoded generator: `'S-' + id + ' · ' + 'Mon Day, YYYY'`, i.e.
  identifier and date are pre-joined into one pre-formatted string, never two separate bindings),
  `{{ s.duration }}` (pre-formatted, e.g. `"2h 15m"`), `{{ s.tokens }}` (pre-formatted, M/K
  suffixed). This settles research risk #1 conclusively: there is no independent "identifier" or
  "date" column binding to worry about — the response's `meta` field must itself be a pre-formatted
  composite, or the frontend must compose it from two raw fields the mockup never separately binds.
  See § Open questions for which approach this PRD picks.
- Values arrive pre-formatted per `docs/design/README.md`, except where this codebase's
  established split keeps a field raw for computation (ADR-0009 precedent, `personal-usage-api`'s
  `CommandEntry.count` / `DailyTokenPoint.tokens`) — see FR below for exactly which fields.
- Mockup's own client-side pagination uses `sesPageSize = 20` — corroborates, not merely
  by-analogy, the story Decision log's `page_size=20` default choice.
- Pagination convention conflict (story AC-3 vs shipped code) — see § Open questions /
  Functional requirements; resolved against shipped code, not story prose.
- Per `roles-from-harness-file-not-keycloak`: this story does not touch program roles at all —
  `individual_usage_visibility` gates on `current_user.user_id`/persona only, never
  `program_roster` or Keycloak groups. No conflict to flag.

## Solution sketch

Add `GET /api/personal-usage/{user_id}/sessions` to the existing `app/api/personal_usage.py`
router, gated by `individual_usage_visibility` (self always, else `cio` only — identical gate
SHP-02 already uses). A new `fetch_sessions_paginated()` service function queries `user_sessions`
by `user_id`, ordered `started_at DESC` with a deterministic tiebreak, paginated via the shared
`get_page_params()` dependency (clamp, not reject, per `api-conventions`). Returns
`{items, page, page_size, total}`, matching the `activities.py` pagination-shape precedent. On the
frontend, the existing "MY SESSIONS TABLE" region on the Architect/Developer/Product-Manager
dashboards binds to this endpoint (dashboard composition itself is out of scope, owned by
ARC-01/DEV-01/PMD-01).

## Scope

- In:
  - `GET /api/personal-usage/{user_id}/sessions` route + response schema, added to the existing
    `app/api/personal_usage.py` / `app/schemas/personal_usage.py` (or a sibling
    `personal_sessions.py` schema module).
  - `fetch_sessions_paginated()` service: query `user_sessions` filtered by `user_id`, ordered
    `started_at DESC, id ASC` (tiebreak), paginated via `get_page_params()`.
  - `individual_usage_visibility` wired as the route's RBAC gate (reused unchanged from SHP-02).
  - Empty-result `200` with `items: [], total: 0` (AC-5).
  - Response field mapping per § Functional requirements (composite `meta` field vs raw
    identifier/date — resolved in FR-1).
- Out:
  - Dashboard composition beyond this one table (layout, other panels on ARC-01/DEV-01/PMD-01).
  - Any write/ingest path into `user_sessions` — owned by upstream ingest stories.
  - The mockup's own pagination-button chrome build-out beyond binding to already-shipped
    frontend pagination components (per story NFR — "reused frontend components").
  - Cross-program session listing — this endpoint is per-user across all their programs, matching
    SHP-02's `personal-usage-api`'s no-`program_id` cross-program-aggregate scope; no
    `program_id`-filtered variant is in scope here.

## Functional requirements

FRs trace 1:1 to story ACs; see `docs/stories/SHP-03.md` for canonical wording.
New impl constraints introduced below:

**SHP-03-FR-1** — Response shape, field-by-field, and the composite-`meta` resolution
*(extends AC-1 with: concrete wire shape)*

```
GET /api/personal-usage/{user_id}/sessions?page=&page_size=

{
  "items": [
    {
      "title": string,          // user_sessions.name, verbatim — the mockup's `s.title`
      "meta": string,            // pre-formatted "S-<n> · <Mon Day, YYYY>" composite —
                                  // mirrors the mockup's own `s.meta` generator exactly:
                                  // session_identifier + " · " + started_at formatted as
                                  // "Mon Day, YYYY" (no year-less short form, unlike
                                  // releases-api's "Jul 15" — mockup literal includes year)
      "duration": string,        // pre-formatted "XhYYm" from duration_seconds
                                  // (app.utils.format.format_duration, api-conventions contract)
      "tokens": string           // pre-formatted M/K-suffixed from tokens
                                  // (app.utils.format.format_number, api-conventions contract)
    }
  ],
  "page": int,
  "page_size": int,
  "total": int
}
```

The mockup binds exactly 3 visible columns (`Session` / `Duration` / `Tokens`) and one composite
sub-line inside the `Session` cell (`s.title` + `s.meta` stacked). This response ships `meta` as a
single pre-formatted string built server-side from `session_identifier` and `started_at` — not two
separate raw fields — because the mockup never binds them independently (verified against the
decoded mockup's row-anatomy markup and its embedded sample-data generator). `duration` uses
`format_duration()` (existing `api-conventions` utility, same as everywhere else in this codebase);
`tokens` uses `format_number()`. Neither ships a raw-int sibling: unlike `DailyTokenPoint.tokens`
(ADR-0009 amendment) or `CommandEntry.count`, nothing downstream of this table needs to compute
with `duration`/`tokens` as numbers — the table is a terminal display surface, not a chart/bar-width
input — so the raw-int exception does not apply here. `page`/`page_size`/`total` are raw ints,
matching every other paginated-list envelope in this codebase (`activities.py` precedent).

**SHP-03-FR-2** — Ordering: `started_at DESC`, deterministic tiebreak *(extends AC-1/AC-2 with:
explicit ORDER BY)*

`fetch_sessions_paginated()` orders `ORDER BY started_at DESC, id ASC`. The `id` tiebreak (the
table's own primary key, a UUID string) is required because `started_at` is not guaranteed unique
across sessions and `LIMIT/OFFSET` pagination without a fully deterministic order can return
duplicate or skipped rows across page boundaries. This directly addresses research risk #2
(MED — "pagination without ORDER BY yields arbitrary order").

**SHP-03-FR-3** — Pagination: clamp, never reject, above `page_size=100` *(supersedes story AC-3,
see § Open questions)*

The route uses the shared `get_page_params()` dependency
(`app/dependencies/pagination.py:25-30`) unchanged: `page` defaults to `1`, `page_size` defaults to
`100` when omitted and is **clamped** to `MAX_PAGE_SIZE=100` when supplied above that value — it is
never rejected with `HTTP 400`. This directly contradicts story AC-3's "returns `HTTP 400` via an
explicit check" claim. Evidence: `app/dependencies/pagination.py`'s own module docstring states
"both helpers CLAMP an out-of-range value to the documented max instead of rejecting it
... Query(..., le=N) would raise HTTP 422 ... which is the opposite of AC 3/AC 4's required
behaviour" (BED-02's own AC, D-01); every shipped consumer of this pattern
(`/api/overview/program-board`'s `page_size`, `/api/overview/program-detail/{id}/releases`'s
`limit`) clamps, never rejects (README.md, "clamp-not-reject style"). The `api-conventions`
contract (`docs/requirements/api.md#api-conventions`) documents the clamp behavior for
`get_page_params`/`get_offset_limit` explicitly and reserves the 400-on-invalid-value rejection
behavior for `validate_range()` (the `?range=` param) only — it does not extend that rejection rule
to pagination. Story AC-3 is a **PRD-vs-story gap**: the story's own Decision log admits this is an
"assumption" extending a range-specific rule to pagination, which the shipped `api-conventions`
contract and every prior consumer contradict. This PRD does not implement AC-3 as written; the
story should be corrected at its next edit (carry-forward, not reopened here).

Per the story's own default choice (`page=1, page_size=20`) versus `get_page_params()`'s shipped
default (`page_size=100`): this route sets its own explicit `Query(20, ge=1)` default for
`page_size` (overriding the dependency's default the same way `personal_usage.py`'s
`_range_with_default` wrapper overrides `validate_range`'s default), since the mockup's own
`sesPageSize = 20` corroborates 20 as the intended default — while still delegating the
clamp-to-100 ceiling to the shared dependency unmodified.

**SHP-03-FR-4** — RBAC: identical gate and denial-logging to SHP-02 *(extends AC-4 with: reuse,
not reimplementation)*

`individual_usage_visibility(current_user, user_id)` (self always, else `cio` only) is called bare,
unchanged, the same call shape `personal_usage.py`'s existing `get_personal_usage()` route already
uses. Denial is `HTTPException(403)` with no data body, logged as `individual_view_denied` by the
check itself (denial-only, no "authorized" event) — this route adds no additional logging around
the gate call, matching the precedent SHP-04-FR-2 established for `governance_visibility`.

## Non-functional requirements

- Performance: page-navigation refresh responds in ≤ 2s (sourced from story NFR). Query is a
  single indexed lookup (`ix_user_sessions_user_id_started_at` on `(user_id, started_at)`) with
  `LIMIT/OFFSET` bounded by `page_size ≤ 100` — no N+1, per `.claude/rules/performance-baseline.md`.
- Security: Per `.claude/rules/security-baseline.md`: applies to the new
  `GET /api/personal-usage/{user_id}/sessions` endpoint. `individual_usage_visibility` enforced
  server-side, never UI-only hiding — reused unchanged from SHP-02, no new gate logic.
- Accessibility: Per `.claude/rules/accessibility-baseline.md`: applies to the "Your session-wise
  usage" table UI on the Architect, Developer, and Product Manager dashboards. Pagination controls
  are reused, unchanged frontend components (story NFR) — sortable-column and live-region rules
  from the baseline apply to those existing components, not new work here.
- Observability: `individual_view_denied` logged via structured JSON output on every RBAC denial
  (reused, unmodified from SHP-02's existing gate).

## Screen inventory

Scoped to the "Your session-wise usage" table region (mockup comment `<!-- MY SESSIONS TABLE -->`)
— byte-identical across the Architect, Developer, and Product Manager dashboard mockups
(`docs/design/mockups/{Architect,Developer,Product Manager} Dashboard.html`); treated as one
screen per `docs/design/README.md` § Screen inventory, not three (same precedent as SHP-04).

| Screen | Route | Render | Primary purpose | States | Story ACs covered |
|---|---|---|---|---|---|
| Your session-wise usage table | — (embedded panel on `/architect`, `/developer`, `/product-manager` dashboard routes — ARC-01/DEV-01/PMD-01) | server (initial load, composed into the parent dashboard page) | Paginated list of the signed-in user's own AI coding sessions | Populated / Loading (20 skeleton rows per `hint-placeholder-count="20"`) / Empty (zero sessions, AC-5) / Error (403 cross-user non-cio access, AC-4) | AC-1, AC-2, AC-3, AC-4, AC-5 |

## Visual spec

See [DESIGN.md](./DESIGN.md) — screen anatomy, bindings, value formats, tokens, and the five
mockup-vs-story divergences (notably the pre-joined `meta` string and the mockup's client-side
pagination).

## Rollout plan

- **Strategy**: bang-bang — new route handler, additive to an existing router; no existing
  behaviour changed. Per `.claude/rules/reusability-baseline.md`, no config-switch forks the call
  graph.
- **Feature flag**: none.
- **Backout plan**: remove the `GET /api/personal-usage/{user_id}/sessions` route from
  `personal_usage.py`; the "MY SESSIONS TABLE" region on the consuming dashboards falls back to
  its existing loading/empty state until ARC-01/DEV-01/PMD-01 stop calling it.
- **Success signal**: an authorized session's `GET /api/personal-usage/{user_id}/sessions` returns
  200 with rows ordered most-recent-first, within the 2s page-navigation budget; a cross-user
  non-`cio` request gets 403 with no data body; verified in staging before ARC-01/DEV-01/PMD-01
  compose against it.

## Documentation requirements

- **README updates**: `README.md` API table — add a
  `GET /api/personal-usage/{user_id}/sessions` row (request, response shape, 403 case,
  empty-list case, clamp-not-reject `page_size` behavior), matching the existing
  `/api/personal-usage/{user_id}` row's format and level of detail.
- **Runbook**: none.
- **API reference**: FastAPI's generated `/docs` (OpenAPI); the new response schema documents
  itself, no separate file.
- **Inline code comments**: `app/api/personal_usage.py` — the new route's docstring must note (a)
  the `meta` composite-string contract (identifier + formatted date, not two fields), (b) the
  `ORDER BY started_at DESC, id ASC` requirement and why the tiebreak is needed, and (c) that
  `page_size` clamps rather than rejects, contradicting the story's own AC-3 text (so a future
  editor doesn't "fix" it back to a 400).
- **Examples / how-to**: none.

## Open questions

- [NEEDS CLARIFICATION: story AC-3 asserts `HTTP 400` on `page_size > 100`; shipped
  `get_page_params()` and every existing consumer (`program-board`, `program-detail/releases`)
  clamp instead. This PRD implements the clamp (FR-3) as the only behavior consistent with shipped
  code and the `api-conventions` contract, and treats AC-3 as a story-authoring error to correct
  at the story's next edit — but a PO sign-off on that correction has not happened yet.]

Decisions logged in `docs/stories/SHP-03.md` § Decision log.

## Approvals

- **2026-09-18** — Pratik Pawar (PO + Designer + BA; single-approver mode): **APPROVE**
  - Recorded at the `/arh-plan-requirements` Phase 4 Product Gate, in response to the gate
    prompt. (An earlier draft of this section was pre-written by `product-spec-agent` during
    Phase 1, before the gate ran; it has been replaced by this actual outcome.)
  - Feature Summary, Functional Requirements, and User Flows reviewed.
  - UI specification reviewed via [DESIGN.md](./DESIGN.md) — hand-authored in Phase 2 because
    `ux-agent` is not installed in this repo (seventh occurrence; carry-forward).
  - Edge Cases, Open Questions, and test-case completeness reviewed.
  - No-placeholder check ✓ · coverage audit `uncovered: []` · 11/11 test cases automatable.
  - `[NEEDS CLARIFICATION]` count = 1 — `page_size > 100` clamp-vs-400. Story AC-3 asserts
    `HTTP 400`; shipped `get_page_params()` and every existing consumer clamp. This PRD
    implements the clamp (FR-3) and treats AC-3 as a story-authoring error to correct at the
    story's next edit. Approved with that correction outstanding; not blocking implementation.
    `SHP-03-TC-06` tests the clamp and carries flip instructions if the ruling changes.
  - Research verdict GO — no conditions to address.
  - Tracker: story pratikpawar009/Dashboard#31 · research #490 · PRD #491.
