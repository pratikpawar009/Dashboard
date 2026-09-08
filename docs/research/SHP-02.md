# Research: SHP-02 — Personal usage panel: cards + daily token chart + commands

**Story**: SHP-02 (Validated)
**Status**: Research complete — 0 open clarifications
**Date**: 2026-09-07

## Upstream dependency summary

Four contract dependencies, all merged to `main` and independently verified in this worktree:

| Dep | Contract | phase | research_verdict | Verified state |
|---|---|---|---|---|
| BED-01 | `db-schema` | review | GO-WITH-CONDITIONS | 18-table schema + migration present, `services/api/app/models/{rollup,ingestion}.py` |
| AUTH-01 | `session` | review | GO-WITH-CONDITIONS | `get_current_user`/`CurrentUser` fully wired, `app/core/auth.py` |
| AUTH-03 | `rbac-checks` | security-review (PR 129, merged to `main` at `815aad1`) | GO-WITH-CONDITIONS | `individual_usage_visibility` shipped, tested, `app/core/rbac.py` |
| BED-02 | `api-conventions` | review | GO-WITH-CONDITIONS | `validate_range`/`format_number`/`format_duration` shipped, `app/dependencies/range.py`, `app/utils/format.py` |

All four are usable today — no stub-building required. AUTH-03's rbac.py (PR 129) is confirmed merged into `main` (`git log --oneline main -- app/core/rbac.py` → `815aad1`), not still pending despite `phase=security-review` in the state index.

## Exploration Log

- `git status` / `git log` → clean branch `feature/SHP-02`, diverges from `main` only in doc files; all backend code (BED-01/02, AUTH-01/03, PGD-01) already on `main`.
- `find services/api/app -name "*.py"` → real layout is `services/api/app/{api,auth,core,dependencies,models,schemas,services,utils}/`, not `backend/app/...` the story's Test mapping names.
- `find apps/web/src` → no `PersonalUsage*`/`MyUsage*`/`Kpis` components exist; SHP-02's own NFR note ("panel components are reused frontend components (unchanged)") + PRD Source column (`frontend/.../PersonalUsageCards.tsx (unchanged)` etc., `docs/prd/ai-sdlc-adoption-dashboards.md:312-316`) + RTM (`ARC-01`/`DEV-01`/`PMD-01` are the declared `consumed_by` composers) confirm SHP-02 is **backend-only** — no `apps/web` changes.
- Read `app/api/overview.py`, `app/api/programs.py` (AUTH-04/PGD-01) — canonical router pattern: module docstring cites every FR/AC/D-decision, `Depends(get_current_user)` + `Depends(get_db)`, one `rbac.*` gate call, fixed presentation-constant tuple zipped with per-row values, one structured log event per outcome path.
- Read `app/core/rbac.py` — `individual_usage_visibility(current_user, target_user_id)`: self always passes (no persona resolution on that path), else persona must be `cio`; denial raises bare `HTTPException(status_code=403)` (no `detail=`) and logs `individual_view_denied` — matches AC4 verbatim, including its "no data body" requirement (`app/core/errors.py`'s handler renders `{"error": {"code": "http_403", "message": "Forbidden", "details": null}}` for a bare 403 — no payload fields).
- Read `app/dependencies/range.py` + `tests/unit/test_range_validation.py` — `validate_range(request, range: str = Query(...))` is **required**, not defaulted; both of BED-02's own reference test routers wire it bare (`Depends(validate_range)`, no default), and `docs/requirements/api.md` states wiring the default is "explicitly each downstream story's own scope." AC5's "default to 30d when omitted" is therefore unimplemented anywhere today — SHP-02 is first to need it.
- Read `services/api/app/models/rollup.py` + `ingestion.py` + `migrations/versions/001_initial_schema.py` — cross-checked against `docs/requirements/data.md`:
  - `user_sessions` (per-session rollup: `user_id, program_id, session_identifier, name, started_at, duration_seconds, tokens`) has **no index at all** beyond the `session_identifier` uniqueness — confirmed absent in both the ORM model (`rollup.py:168-178`, no `__table_args__`) and the migration (`grep create_index` shows zero `user_sessions` index statements).
  - `usage_events` (raw per-command event log; carries `user`, `command`, `ts`, `total`/`input_tokens`/`output_tokens`) has four indexes, **all `program_id`-prefixed** (`ix_usage_events_program_id_{ts,user,command,session_id}`) — none usable for a query filtered on `user` alone.
  - `usage_events` retention/archival is explicitly out of scope for BED-01 (`data.md:55`) — the table grows unboundedly, org-wide.
  - `personal-usage-api`'s own endpoint (`GET /api/personal-usage/{user_id}`) carries **no `program_id`** — "my usage" is a cross-program aggregate by contract, which means neither table's only usable indexes (all program_id-first) narrow the scan at all for this endpoint's access pattern.
- Read `tests/perf/test_overview_perf.py` — established perf-test convention: real `create_app()`, dev-bypass-minted bearer token, a SQLAlchemy `before_cursor_execute` query-count spy asserting a bounded SELECT count, `time.perf_counter()` against a fixed budget, plus log-content/PII assertions. This is the pattern SHP-02's own perf test should mirror.
- Decoded mockups (already extracted this session, `.../developer-dashboard.doc.html` et al., section lists md5-identical across Architect/Developer/Product Manager):
  - `myKpis` cards bind **5** fields in the HTML template — `k.iconBg`, `k.iconColor`, `k.glyph`, `k.value`, `k.label` (lines 419-423) — not the 3 the story AC1 / `api.md`'s `personal-usage-api` shape line name. The JS mock-data generator's `mkKpis()` (line 870) also produces a `k.delta` field, but grep across all three decoded mockups confirms `{{ k.delta }}` is **never bound** in any template — dead field, must not appear in the response.
  - `commands[].barStyle` mirrors `dot_style_for_program()`'s already-shipped pattern (`app/utils/format.py`) — a server-computed, ready-to-bind CSS string — but its width formula is `round(count / max(all counts in range) * 100)%` (mockup line 999: `cmax = Math.max(...cmdCounts)`), **not** `count / total * 100` as AC3's prose ("a bar proportional to its share of the total run count") literally reads.
  - `tokChart` has a direct in-repo precedent: `overview-token-series-api` (OVW-02, `docs/requirements/api.md:93-100`) returns "exactly 12 {month, value} points" — a raw numeric series, not server-rendered chart markup. The design README's own flagged decision ("templates also bind presentation... decide deliberately, do not copy the mockup here") has already been resolved this way for every prior story (`dotStyle`, `ProgramSummaryCard`) — no fresh decision needed for the numeric-series question, only for which fields carry literal CSS (glyph-card colors, bar width/color).
- Read `docs/requirements/RTM.md` § Decisions (2026-09-07 entry) — confirms the AC3-descope was verified via the same three-mockup decode and is settled, cross-referenced against the still-open `PGD-06`/`EMD-01` session-series drift (not SHP-02's concern).

## Pattern map

### Existing code to extend
- None — `personal_usage.py` router/service/schema are wholly new files; nothing existing gains new callers.

### Existing patterns to follow
- **Router shape**: mirror `app/api/overview.py` — module docstring naming every FR/AC/decision, `Depends(get_current_user)` + `Depends(get_db)`, exactly one `rbac.individual_usage_visibility(current_user, user_id)` gate call, one structured log event per branch.
- **Fixed-presentation-constant cards**: mirror `overview.py`'s `_SUMMARY_CARD_GLYPHS_LABELS` tuple-zip — extend to `(glyph, iconBg, iconColor, label)` 4-tuples (order: Sessions, Total time, Total tokens, Avg tokens/session) sourced verbatim from the decoded mockup, zipped with the one varying `value` per card.
- **CSS-in-response precedent**: `dot_style_for_program()` (`app/utils/format.py`) is direct precedent for `commands[].barStyle` — same "ready-to-bind CSS declaration, computed server-side" shape; reuse the module, add a new `bar_style_for_share(count, max_count, color)`-style helper there (or a story-local equivalent) rather than re-deriving the CSS-in-API decision from scratch.
- **Range validation reuse**: `validate_range`/`range_to_start` (`app/dependencies/range.py`) for the 7d/30d/90d membership check + 400 rejection + window-start math — reused, not reimplemented, via a thin story-local wrapper (see Risk #2).
- **Formatting reuse**: `format_number` (M/K) for tokens/counts, `format_duration` (h/m, minutes in) for `total_time` — both from `app/utils/format.py`, matching `docs/requirements/api.md#api-conventions`'s "values arrive pre-formatted" rule.
- **Zero-denominator handling**: `compute_average` (`app/services/rollup_compute.py`) already establishes the `0.0`-when-`count==0` convention for an averaged field — `avg_tokens_per_session` should follow that precedent, not `adoption_percent`'s `None`-on-zero precedent (a session count of 0 for a brand-new user is the "measured and zero" case, not "nothing to measure").
- **Perf-test shape**: mirror `tests/perf/test_overview_perf.py` — query-count spy + `time.perf_counter()` budget assertion + log-content/PII checks, run against the real `create_app()`.

### New files to create
- `services/api/app/api/personal_usage.py` — router (`GET /api/personal-usage/{user_id}`), registered in `app/main.py` after `overview_router`.
- `services/api/app/services/personal_usage.py` — query/aggregation logic (cards, daily series, commands breakdown), pure-DB-input functions per BED-02's D-02 precedent (services layer takes fetched rows, doesn't own transaction boundaries beyond its own queries).
- `services/api/app/schemas/personal_usage.py` — `PersonalUsageCard` (`glyph, value, label, iconBg, iconColor`), `DailyTokenPoint` (or similar), `CommandEntry` (`cmd, count, barStyle`), `PersonalUsageResponse` envelope.
- `services/api/migrations/versions/<rev>_personal_usage_indexes.py` — new indexes (Risk #1).
- `services/api/tests/unit/test_personal_usage.py`, `services/api/tests/perf/test_personal_usage_perf.py`.

### Shared code at risk
- `services/api/app/dependencies/range.py` — do not edit; wrap locally instead (Risk #2).
- `services/api/app/models/rollup.py` / `ingestion.py` + the existing Alembic migration — adding indexes here is an additive migration, but it is schema BED-01 already shipped and reviewed; coordinate rather than silently altering `001_initial_schema.py` in place (add a new revision, don't hand-edit the merged one).

## Risk register

| # | Dimension | Severity | Description | Mitigation |
|---|---|---|---|---|
| 1 | Performance | HIGH | No index supports this story's core query pattern (`user`/`user_id` filter, no `program_id` to narrow it). `user_sessions` has zero indexes beyond `session_identifier` uniqueness; `usage_events`'s 4 indexes are all `program_id`-prefixed; `usage_events` has no retention policy (unbounded, org-wide growth, `data.md:55`). NFR-002 (≤2s refresh) is at real risk. | New Alembic migration adds `Index("ix_user_sessions_user_id_started_at", "user_id", "started_at")` and `Index("ix_usage_events_user_ts", "user", "ts")`. Cards/daily-chart query `user_sessions` (already session-granular with `tokens`/`duration_seconds`); only the commands panel touches `usage_events`. Add a query-count-spy perf test mirroring `tests/perf/test_overview_perf.py` asserting bounded SELECTs + duration under budget. |
| 2 | Integration | MED | `validate_range`'s only signature is `Query(...)` (required) — AC5's "default 30d when omitted" is unimplemented anywhere in the codebase (BED-02's own reference tests don't exercise it either). | Story-local wrapper dependency: `def _range_with_default(request: Request, range: str = Query("30d")) -> str: return validate_range(request, range)` — supplies the default at the `Query` level, delegates membership-check/400/logging to the shared function. No edit to `app/dependencies/range.py`. |
| 3 | Domain | MED | AC3 ("bar proportional to its share of the **total** run count") and the decoded mockup's actual formula (`count / max(counts) * 100` — proportional to the largest single command) disagree. | Resolve as a documented Decision before coding: per CLAUDE.md § Design system the mockup settles response *values*; use `count / max(counts) * 100`, record the AC-vs-mockup discrepancy explicitly so it isn't mistaken for an implementation bug later. |
| 4 | Domain | LOW | `myKpis` cards need 5 bound fields (`glyph, value, label, iconBg, iconColor`) per the decoded mockup; the story AC1 / `api.md` contract line name only the 4 card *identities* and their `value`. `k.delta` exists in the mockup's mock-data JS but is never bound in any of the three templates — must not be added. | Model `PersonalUsageCard` with all 5 fields, values read directly off the decoded mockup (not invented); omit `delta`. |
| 5 | Compatibility | MED | 4 downstream stories (ARC-01, DEV-01, PMD-01, PGD-05) already declare a hard RTM dependency on `personal-usage-api` before any are implemented — SHP-02 is the one chance to lock the shape; a later addition (e.g. discovering the missing `iconBg`/`iconColor` fields post-ship) is a 4-way breaking change. | PLAN.md's schema design reviewed field-by-field against the decoded mockup for all 3 panels before implementation starts, not just against `api.md`'s terse shape line. |
| 6 | Dependency | LOW | Story's Test-mapping section names `backend/app/routers/personal_usage.py` / `backend/app/services/personal_usage.py`, which don't exist in this repo. | Correct to `services/api/app/api/personal_usage.py` / `services/api/app/services/personal_usage.py` in PLAN.md's file plan (same drift already found and fixed for BED-02 — see `docs/research/BED-02.md`). |
| 7 | Domain | LOW | `personal-usage-api` carries no `program_id` — "my usage" aggregates across every program a user has touched. PGD-05 reuses this same endpoint verbatim for its per-member popup inside one program's Project Team panel, so that popup will show the same org-wide number regardless of which program's team page opened it. Settled by contract (`docs/requirements/RTM.md` § Decisions, 2026-08-26 fold entry), not new drift — but compounds Risk #1 (no `program_id` to narrow the scan). | No action for SHP-02; carry-forward note to PGD-05's own planning that its popup is intentionally org-wide, not program-scoped. |

## Score

| Dimension | Weight | Score | Rationale |
|---|---|---|---|
| Integration | 25 | 88 | All 4 upstream contracts merged to `main`, working, tested (`get_current_user`, `individual_usage_visibility`, `validate_range`, `format_*`). Only gap: the default-range wiring nobody has built yet (Risk #2), well-understood and cheaply closed. |
| Compatibility | 20 | 82 | No live consumers yet (ARC-01/DEV-01/PMD-01/PGD-05 all still `story-validated`), so nothing to break today — but 4 declared future consumers raise the cost of shipping an incomplete shape (Risk #5). |
| Domain | 20 | 72 | FR-SH-06 descope correctly bounded and non-reintroducible; several real but individually-resolvable open judgment calls surfaced (bar formula vs. AC prose, full card field set, zero-session averaging, cross-program scope) — none blocking, all need explicit Decisions before coding. |
| Performance | 15 | 42 | NFR-002 (≤2s) is explicit, but the schema this story must query has **no usable index** for its access pattern on either candidate table, against an explicitly-unbounded raw event log (Risk #1). Addressable within this story's own scope (a new migration + query-count-spy perf test), not a structural blocker — but real, unaddressed work today. |
| Dependency | 20 | 95 | All 4 upstream stories `impl: complete`, reviewed `PASS`/in security-review, verified present and usable on this branch; no blocking external work. |

**Total: 78/100 → GO-WITH-CONDITIONS**

## Conditions for GO

1. New Alembic migration adds `user_sessions(user_id, started_at)` and `usage_events(user, ts)` indexes; a query-count-spy perf test (mirroring `tests/perf/test_overview_perf.py`) asserts bounded SELECT count + duration under NFR-002's ≤2s budget.
2. DECISIONS.md records, before coding, which table backs each panel: `user_sessions` for the 4 cards + daily token chart (session-granular, already has `tokens`/`duration_seconds`), `usage_events` only for the commands breakdown.
3. Default-range-when-omitted (AC5) is wired via a story-local wrapper around the shared `validate_range` (Risk #2) — no edit to `app/dependencies/range.py`.
4. `PersonalUsageCard` ships the full 5-field set (`glyph, value, label, iconBg, iconColor`) sourced from the decoded mockup, order-locked, mirroring `overview.py`'s constant-tuple pattern; `commands[].barStyle`'s width formula (`count / max(counts)`, not `/ total`) is recorded as an explicit Decision against AC3's prose.
5. PLAN.md's file plan uses the real paths (`services/api/app/api/personal_usage.py`, `services/api/app/services/personal_usage.py`) — no `backend/app/...`.

## Synthesis

GO-WITH-CONDITIONS. Every upstream contract SHP-02 needs — session, RBAC, range validation, the 18-table schema — is already merged to `main` and directly verified working in this worktree, and the FR-SH-06 descope is cleanly bounded with no leftover scope creep. The score lands at 78 rather than higher because of one concrete, evidenced gap: neither `user_sessions` nor `usage_events` carries an index usable for this endpoint's actual access pattern (a cross-program, per-user filter), and `usage_events` has no retention policy, so a naive implementation risks blowing the ≤2s NFR-002 budget as the org-wide event log grows — confirmed by reading the ORM models, the Alembic migration, and the schema contract directly, not inferred. That's the single biggest risk (Risk #1) and it's fully addressable within this story's own scope via a new migration and a perf test modeled on the existing `test_overview_perf.py` pattern. A second cluster of lower-severity Domain risks — the commands bar's max-vs-total formula, the cards' full 5-field shape, cross-program aggregation semantics — are all resolvable from the already-decoded mockups and existing in-repo precedent (`dot_style_for_program`, `_SUMMARY_CARD_GLYPHS_LABELS`) rather than requiring new product input, so 0 clarification markers were needed. Next step: `/arh-plan-requirements SHP-02`, with PLAN.md required to address all 5 conditions above explicitly.

## Clarifications

<!-- None open. -->
