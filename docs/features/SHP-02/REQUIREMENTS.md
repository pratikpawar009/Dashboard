# Feature: SHP-02 — Personal usage panel: cards + daily token chart + commands

## Problem

Architect, Developer, and Product Manager personas have no way to see their own AI usage — how
many sessions they ran, how much time and tokens they spent, and which commands they ran most —
without querying the database directly. SHP-01 gives every persona dashboard a header shell, but
no data. ARC-01, DEV-01, and PMD-01 all declare a hard RTM dependency on this story's
`personal-usage-api` contract and cannot compose their "Your usage" panel until it exists;
PGD-05 depends on it too, for its own per-member popup.

## Outcome

`GET /api/personal-usage/{user_id}` returns, for the signed-in user viewing their own usage (or
a `cio` viewing anyone's), four summary cards, a ranged daily token series, and a ranged command
breakdown, in ≤2s. Any other cross-user request is denied server-side with no data body. ARC-01,
DEV-01, PMD-01, and PGD-05 can compose against a locked response shape from day one.

## Constraints

- Four upstream contracts, all merged to `main` and independently verified working: `db-schema`
  (BED-01), `session` (AUTH-01), `rbac-checks` (AUTH-03, `individual_usage_visibility`),
  `api-conventions` (BED-02, `validate_range`/`format_number`/`format_duration`). None require
  stub-building.
- Neither candidate table carries an index usable for this endpoint's actual access pattern
  (cross-program, per-`user`/`user_id` filter): `user_sessions` has none beyond
  `session_identifier` uniqueness; `usage_events`'s four indexes are all `program_id`-prefixed.
  `usage_events` also has no retention policy (`docs/requirements/data.md:55`) and grows
  unboundedly, org-wide. NFR-002's ≤2s budget is at real risk without a new migration
  (Addressing Research Conditions, C-1).
- The endpoint takes no `program_id` — "my usage" is a cross-program aggregate by contract
  (`docs/requirements/api.md#personal-usage-api`). `PGD-05` reuses this same contract verbatim
  for a per-member popup inside one program, so that popup necessarily shows an org-wide figure
  regardless of which program opened it — settled by `docs/requirements/RTM.md` § Decisions,
  2026-08-26, not new drift.
- FR-SH-06 (daily session-time chart) is descoped from this story (Decision log, 2026-09-07):
  all three persona mockups are md5-identical in section list and bindings, and the only chart
  binding present is `{{ tokChart }}`. `personal-usage-api`'s shape carries cards + daily token
  series + commands only — no second chart.
- This is a backend-only story: no `apps/web` change. The mockups still settle response shape
  per `CLAUDE.md` § Design system (`myKpis` card fields, `commands[].barStyle` formula) even
  though no screen is rendered by this story itself.

## Solution sketch

A new router (`GET /api/personal-usage/{user_id}`), service, and schema layer: cards and the
daily token chart are computed from `user_sessions` (already session-granular, carries `tokens`
and `duration_seconds`); the commands breakdown is computed from `usage_events` only. Access is
gated by `rbac-checks`' `individual_usage_visibility` (self always, else `cio`); range defaults
and validates via a thin story-local wrapper around the shared `validate_range`; every numeric
value is formatted server-side via `format_number`/`format_duration`. A new additive Alembic
migration adds the two indexes this access pattern needs. Card fields, chart shape, and the
commands bar-width formula are read directly off the decoded ARC/DEV/PMD mockups, not invented
from AC prose where the two disagree.

## Addressing Research Conditions

Research verdict: GO-WITH-CONDITIONS, score 78/100, 5 numbered conditions from
`docs/research/SHP-02.md` § "Conditions for GO":

- **C-1: No usable index for this endpoint's access pattern** — a new Alembic migration
  (`services/api/migrations/versions/<rev>_personal_usage_indexes.py`) adds
  `Index("ix_user_sessions_user_id_started_at", "user_sessions", "user_id", "started_at")` and
  `Index("ix_usage_events_user_ts", "usage_events", "user", "ts")`;
  `services/api/tests/perf/test_personal_usage_perf.py` mirrors `tests/perf/test_overview_perf.py`'s
  query-count-spy + `time.perf_counter()` pattern, asserting a bounded SELECT count and duration
  under NFR-002's ≤2s budget, across all three ranges (Scope, NFR — Performance).
- **C-2: Table-to-panel mapping fixed before coding** — `user_sessions` backs the 4 cards and the
  daily token chart; `usage_events` backs only the commands breakdown. Recorded here; mirrored
  into a `DECISIONS.md` entry at the Plan phase per the condition's own wording.
- **C-3: Default-range wiring without touching the shared dependency** — AC5's "default 30d when
  omitted" is wired via a story-local wrapper dependency
  (`_range_with_default(request: Request, range: str = Query("30d")) -> str: return
  validate_range(request, range)`) that supplies the `Query` default only; the `{7d,30d,90d}`
  membership check, the `HTTP 400` rejection, and the `invalid_range` log event are delegated to
  the shared `validate_range()` unchanged (**SHP-02-FR-6**). `app/dependencies/range.py` itself
  is not edited.
- **C-4: Full card field set and bar formula, sourced not invented** — `PersonalUsageCard` ships
  all 5 mockup-bound fields (`glyph, value, label, iconBg, iconColor`), order-locked, values read
  off the decoded ARC/DEV/PMD mockups (**SHP-02-FR-1**); `commands[].barStyle`'s width formula is
  `round(count / max(all counts in range) * 100)%`, not `count / total * 100` as AC3's prose
  reads — recorded as an explicit Decision against AC3 (**SHP-02-FR-3**, Open questions).
- **C-5: Real file paths in the implementation plan** — `PLAN.md`'s file plan (Phase 2 of
  `/arh-plan-implementation`) must use `services/api/app/api/personal_usage.py` and
  `services/api/app/services/personal_usage.py`; the story's own Test-mapping section names a
  non-existent `backend/app/...` path (research Risk #6) and must not be carried forward.

## Scope

**In:**
- `GET /api/personal-usage/{user_id}` router — `services/api/app/api/personal_usage.py`,
  registered in `app/main.py` after `overview_router`.
- Service layer — `services/api/app/services/personal_usage.py`: cards + daily token series
  query/aggregation over `user_sessions`, commands breakdown over `usage_events`.
- Schemas — `services/api/app/schemas/personal_usage.py`: `PersonalUsageCard`, a daily-token-point
  model, `CommandEntry`, and the response envelope.
- New additive Alembic migration adding the two indexes in C-1.
- Unit tests (`services/api/tests/unit/test_personal_usage.py`) covering all 5 story ACs.
- Perf test (`services/api/tests/perf/test_personal_usage_perf.py`) — query-count spy + duration
  budget, all three ranges.

**Out:**
- FR-SH-06 daily session-time chart — descoped 2026-09-07 (Decision log), unbound in all three
  persona mockups; open cross-epic product question, `docs/requirements/RTM.md` § Decisions
  2026-09-07.
- `usage_events` retention/archival — out of BED-01's scope (`docs/requirements/data.md:55`) and
  out of this story's.
- Paginated personal session list — deferred to **SHP-03**.
- Any `apps/web` component work rendering cards, chart, or commands panel — deferred to
  **ARC-01 / DEV-01 / PMD-01**.
- `k.delta` card field — present in the mockup's mock-data generator, bound in no template;
  must not appear in the response.

## Functional requirements

FRs trace 1:1 to story ACs; see `docs/stories/SHP-02.md` for canonical wording.
New impl constraints introduced below (when any):

**SHP-02-FR-1** — Card field set, order, and the dead `delta` field  *(extends AC1 with: the
exact 5-field shape and field order)*

`PersonalUsageCard` carries `glyph, value, label, iconBg, iconColor` — not just the card
identities and `value` that AC1's prose and `api.md`'s terse shape line name. `glyph`, `label`,
`iconBg`, `iconColor` are fixed server-owned presentation constants sourced verbatim from the
decoded ARC/DEV/PMD mockups (`myKpis`, template lines 419-423), zipped against the one varying
`value` per card — `format_number()` for `sessions`, `total_tokens`, `avg_tokens_per_session`;
`format_duration()` for `total_time` (both `api-conventions`, BED-02). Response order is locked:
Sessions, Total time, Total tokens, Avg tokens/session — mirrors `overview.py`'s
`_SUMMARY_CARD_GLYPHS_LABELS` tuple-zip pattern. `k.delta` (present in the mockup's `mkKpis()`
mock-data generator, line 870) is bound in no template across all three mockups and must not
appear in the response.

**SHP-02-FR-2** — Daily token chart is a raw numeric series, not rendered markup  *(extends AC2
with: the wire shape)*

The `{{ tokChart }}` binding renders client-side from data, following `overview-token-series-api`'s
(OVW-02) precedent of "exactly 12 {month, value} points" for the same class of binding. The daily
token chart returns one `{date, value}` point per day in the selected range (7/30/90 points,
zero-padded for days with no sessions), plus `period_total` and `avg_per_day` — both passed
through `format_number()` per `api-conventions`.

**SHP-02-FR-3** — Commands bar-width formula: max-of-range, not share-of-total  *(extends AC3
with: the concrete formula, which disagrees with AC3's own prose)*

`commands[].barStyle` is a server-computed, ready-to-bind CSS string, mirroring
`dot_style_for_program()`'s (`app/utils/format.py`) established shape. Its width is
`round(count / max(all commands' counts in the selected range) * 100)%` — proportional to the
single largest command in the period, matching the decoded mockup (`cmax =
Math.max(...cmdCounts)`, line 999) — **not** `count / total_run_count * 100` as AC3's prose ("a
bar proportional to its share of the total run count") literally reads. Per `CLAUDE.md` § Design
system the mockup, not story prose, settles response shape; the discrepancy is recorded here and
in Open questions so it is not later mistaken for an implementation bug.

**SHP-02-FR-4** — RBAC denial: bare 403, no data body, fixed envelope  *(extends AC4 with: the
exact response envelope)*

A denial from `individual_usage_visibility` raises a bare `HTTPException(status_code=403)` (no
`detail=`), rendered by the existing `app/core/errors.py` handler as `{"error": {"code":
"http_403", "message": "Forbidden", "details": null}}` — no endpoint-specific fields, no partial
data. `individual_view_denied` is logged on every denial (NFR-011).

**SHP-02-FR-5** — Zero-session average: 0.0, not null  *(extends AC1 with: the zero-denominator
convention for `avg_tokens_per_session`)*

`avg_tokens_per_session` follows `compute_average()`'s `0.0`-when-`count==0` convention
(`app/services/rollup_compute.py`) — a user with zero sessions in the selected range is a
measured-and-zero case, not `adoption_percent`'s "nothing registered yet" `None` case.

**SHP-02-FR-6** — Default-range wrapper, no edit to the shared dependency  *(extends AC5 with:
the mechanism, not just the outcome)*

`range` defaults to `30d` when omitted via a story-local wrapper dependency —
`def _range_with_default(request: Request, range: str = Query("30d")) -> str: return
validate_range(request, range)` — that supplies the `Query` default and delegates the
`{7d,30d,90d}` membership check, the `HTTP 400` rejection, and the `invalid_range` warning log to
the shared `validate_range()` (`app/dependencies/range.py`) unchanged. No edit lands in that
shared module (Condition C-3).

## Non-functional requirements

- Performance: range/filter-change refresh responds in ≤2s p95 (NFR-002, story-sourced). Per
  `.claude/rules/performance-baseline.md`: the query-count-spy perf test
  (`test_personal_usage_perf.py`) asserts a fixed, bounded SELECT count per request — not
  proportional to `usage_events`' unbounded row count — and duration under the 2s budget, across
  all three ranges. Pagination is N/A — no list endpoint in this story (SHP-03 owns pagination).
- Security: Per `.claude/rules/security-baseline.md`: applies to the new
  `GET /api/personal-usage/{user_id}` route. Feature-specific: `individual_usage_visibility`
  enforced server-side only (self always, else `cio`), never UI-only hiding (NFR-005); every log
  line this story emits carries `user_id` only, never `email`/`name`.
- Observability: `individual_view_denied` logged via `structlog`/`logging` JSON output on every
  RBAC denial (NFR-011), mirroring the shape of BED-02's `invalid_range` warning event (route,
  param, rejected/target value), minus any PII field.
- Accessibility: N/A — backend-only story, no rendered surface. NFR-008 (WCAG AA) is satisfied by
  the consuming stories (ARC-01, DEV-01, PMD-01) that render this contract's data.

## Visual spec

Not applicable — `integrations.design = none`. Backend / API / data feature.

## Rollout plan

- **Strategy**: bang-bang — new read-only route, zero live consumers today (ARC-01, DEV-01,
  PMD-01, PGD-05 are all still `story-validated`); nothing to stage or migrate.
- **Feature flag**: none — a purely additive new endpoint plus an additive index migration; no
  existing call graph to fork (`.claude/rules/reusability-baseline.md`).
- **Backout plan**: remove the router registration from `app/main.py`. The additive index
  migration can be downgraded (`alembic downgrade`) independently, without touching
  `user_sessions`/`usage_events` data, since it adds indexes only.
- **Success signal**: `services/api/tests/perf/test_personal_usage_perf.py` passes — p95 < 2s and
  a fixed, bounded SELECT count — across all three ranges (7d/30d/90d), before ARC-01, DEV-01, or
  PMD-01 begin planning against this contract.

## Documentation requirements

- **README updates**: root `README.md` § API table — add a row for
  `GET /api/personal-usage/{user_id}` (bearer auth via the standard dependency; 200 cards +
  daily-series + commands shape; 403 no-body on RBAC denial; 400 on invalid `range`), following
  the AUTH-04/PGD-01 precedent of documenting new routes there.
- **Runbook**: none.
- **API reference**: none beyond FastAPI's generated `/docs` — the root README notes `/docs`
  already covers every route in full; no dedicated reference doc is needed.
- **Inline code comments**: `personal_usage.py` router module docstring names every FR/AC/
  Condition it satisfies, mirroring `overview.py`'s convention; `personal_usage.py` service module
  documents the `user_sessions`-vs-`usage_events` table split (Condition C-2) and the bar-width
  formula's AC3-vs-mockup discrepancy (**SHP-02-FR-3**).
- **Examples / how-to**: none.

## Open questions

<!-- None open. needs_clarification_count: 0.                                                 -->
<!--                                                                                           -->
<!-- Three items previously listed here were not questions but recorded resolutions, and have  -->
<!-- moved to their canonical home in docs/stories/SHP-02.md  Decision log (prd-template        -->
<!-- pins that as the source of truth and forbids a  Resolved questions section here):          -->
<!--                                                                                           -->
<!--   1. FR-SH-06's daily session-time chart, bound in no mockup - descoped 2026-09-07, so it  -->
<!--      is out of this contract entirely. The cross-epic drift it belongs to (FR-PD-15/16     -->
<!--      specify the same chart for Program Detail, equally unbound) is tracked in             -->
<!--      docs/requirements/RTM.md  Decisions, 2026-09-07 - not against this story.             -->
<!--   2. AC3's "share of the total run count" prose vs the mockup's count / max(counts)        -->
<!--      formula - resolved in favour of the mockup per CLAUDE.md  Design system, shipped as   -->
<!--      SHP-02-FR-3 and logged 2026-09-07.                                                    -->
<!--   3. PGD-05's per-member popup showing an org-wide figure - settled by contract            -->
<!--      (RTM  Decisions, 2026-08-26 fold entry), carried forward to PGD-05's own planning.    -->
<!--                                                                                           -->
<!-- Kept as a comment deliberately, matching docs/features/SHP-01/REQUIREMENTS.md and          -->
<!-- docs/features/BED-04/REQUIREMENTS.md: the phase-preconditions clarification gate treats    -->
<!-- ANY non-blank, non-comment line in this section as an unresolved open question and aborts  -->
<!-- the next phase. Prose saying "None" trips it.                                              -->

## Approvals

**APPROVED** — vinit.bhamare@apexon.com, 2026-09-07, via the `/arh-plan-requirements` Product Gate.

One checklist item was failing at approval and was **accepted as a recorded gap**, not silently passed:

| Item | Status at approval | Why accepted |
|---|---|---|
| Test-case coverage audit shows zero uncovered ids | **GAP — `SHP-02-AC-5`, `SHP-02-FR-5`, `SHP-02-FR-6`, `SHP-02-NFR-performance`** | A 2-test-case cap was an explicit instruction for this run (`/arh-plan-requirements SHP-02 do not create more than 2 test cases`). The two slots were spent on the widest-coverage pair: `SHP-02-TC-01` (`type: contract`) asserts the whole response envelope and so covers AC-1/AC-2/AC-3 and FR-1/FR-2/FR-3 together, including the `count / max(counts)` bar formula with seeded data that discriminates it from `count / total`; `SHP-02-TC-02` (`type: security`) covers AC-4, FR-4, NFR-security and NFR-observability. `coverage_audit.uncovered` discloses the four remaining ids rather than reporting a clean audit. |

Other checklist items: `## Screen inventory` correctly omitted and `design = n/a` — backend-only story, no `SHP` epic in `docs/design/schema.json` (Designer-approval item is N/A, not skipped); all 5 research conditions carry concrete mitigations in `## Addressing Research Conditions`; 0 unresolved `[NEEDS CLARIFICATION]` markers (3 non-blocking Open questions, none of them markers); no-placeholder grep returns 0 matches; both test cases carry a `requirement_id` resolving to a really-declared id.

Carrying into `/arh-plan-implementation`: research conditions **C-1** (index migration + bounded-SELECT perf test under NFR-002's ≤2s budget) and **C-3** (the `_range_with_default` wrapper) are committed in this PRD but have **no covering test case** — `PLAN.md` must back both with `tasks.json` entries, since the test-case manifest will not catch a regression in either. `SHP-02-FR-5`'s zero-session `avg = 0.0` branch is likewise untested at the behavioural layer and needs a unit task.
