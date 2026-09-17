# Code Review — feature/PGD-06

- Date: 2026-09-17
- Mode: story (GATE MODE — report-only, invoked from `/arh-implement` Validate ∥ Review gate)
- Files reviewed: 12 (working tree vs `origin/main`, uncommitted)
- Verdict: PASS

## Executive summary

PGD-06 adds a read-only daily session-time series endpoint (`GET /api/overview/program-detail/{program_id}/session-time-series`) plus its Next.js proxy, mirroring the shipped PGD-02/PGD-05 sibling precedents exactly. The AC-1 factual correction (cross-member SUM instead of a `member_id IS NULL` read) is implemented correctly and proven by a real differentiating test, not a status-code-only check. Gate-before-query ordering (FR-6) is structurally enforced and proven with a query-execution spy. The D-02 no-new-index decision is backed by an honest perf guard (query-count + wall-clock, no relaxed budgets). Docs (README, `docs/requirements/api.md`) are updated in the same diff — no contract-drift. All new backend tests (18 unit/integration + 4 perf) and the full frontend vitest suite (298 tests) pass; ruff, mypy, and tsc are clean on the touched files.

🟢 Correct D-01 aggregate semantics, proven by a real cross-member-sum test (not just non-zero/200). Gate-before-query (FR-6) proven structurally via query spy, not just a 403 status code. Perf guard is honest (single-query assertion + wall-clock budget, seeded at TC-17's floors, no loosened thresholds). Docs updated in-diff. Full frontend suite green, zero regressions.
⚠️ None blocking.
🛑 None.

## Findings summary

| Severity | Count | Category distribution |
|----------|-------|------------------------|
| CRITICAL |   0   | — |
| HIGH     |   0   | — |
| MEDIUM   |   0   | — |
| LOW      |   1   | testability (1) |

## Detailed findings

### LOW

#### F-1 — testability: TC-15's differential-range assertion is looser than TC-06/TC-07's
- Category: testability
- Path: `services/api/tests/unit/test_program_session_series_route.py:582-592`
- Source: `.claude/rules/reusability-baseline.md` (test clarity), PLAN.md § 7 (TC-15 mapping)
- Description: `test_each_range_returns_own_window_and_length_tc15` asserts `len(totals) >= 2` (at least two of the three `period_total_seconds` values differ) rather than pinning exact expected sums for 7d/30d/90d given the two seeded rows (day_offset 1 and 45). The service-level TC-06/TC-07 tests in `test_program_session_series_service.py` already pin exact values with a documented rationale, so this is a route-level completeness gap only, not a coverage gap — the underlying arithmetic is proven elsewhere.
- Suggested fix: Optionally tighten to exact expected totals (e.g. `body_7d["period_total_seconds"] == 100`, `body_30d == 100`, `body_90d == 400`) for a stronger regression signal at the HTTP layer; not blocking given service-level coverage already pins this.

## What went well

- D-01 correction implemented precisely: `fetch_program_session_series` computes `SELECT date_trunc('day', date), SUM(session_time_seconds) ... GROUP BY` with no `member_id` filter for the unfiltered view, and `test_cross_member_sum_on_same_day_tc01` seeds two members on the same day and asserts the summed total (4200 = 1800+2400) — this would fail under a regression to `member_id IS NULL`, unlike a test that only checks non-zero/200.
- FR-6 gate ordering is structural, not incidental: `program_visibility` then (conditionally) `member_in_program_visibility` are both `await`ed sequentially before `fetch_program_session_series` is called in `app/api/overview.py::get_program_session_series`, and `test_non_self_non_cio_member_filter_denied_before_query_tc08` proves it with a `before_cursor_execute` query spy asserting zero `session_series` statements on the denied path (plus the `member_view_denied` log).
- D-02's no-new-index acceptance is honestly guarded: `tests/perf/test_program_session_series_perf.py` asserts both a single-query count and a <2000ms wall-clock budget against ≥50 members × 100 days (5,000 rows), for all three ranges plus the self-filtered path, with no loosened assertions and explicit "do not relax" comments.
- Query shape genuinely mirrors `program_detail_token_trend.py`'s `date_trunc`/`GROUP BY` pattern field-for-field (both back onto `DateTime(timezone=True)` columns), so this isn't a superficial "looks similar" claim — it's the same pattern for the same reason.
- Docs kept in sync in the same diff: README's API table row and `docs/requirements/api.md`'s `program-session-series-api` contract block both reflect the shipped shape (raw ints, no-404, cross-member-SUM correction, gate ordering) — no contract-drift.
- AF-01's 403-vs-404 choice is correctly reasoned: `member_in_program_visibility`'s 403 is a persona/gate decision on an open-aggregate program resource (not per-resource ownership), so `.claude/rules/security-baseline.md`'s "404 not 403" IDOR guidance doesn't apply here — it governs foreign-owned resource ids, and this route has no ownership check to leak via 403. The frontend/proxy mapping mirrors PGD-05's already-shipped `/team/{member_id}/usage` precedent exactly, so this isn't a novel choice either.
- No scope creep: all 12 changed files map 1:1 to `tasks.json`'s `file_plan` F-01..F-12; the two out-of-scope untracked paths (`apps/web/src/app/dev-login/`, `services/mcp-server/uv.lock`) were correctly excluded from this review per the task instructions, and `docs/activity/activity.jsonl` / `docs/state/features.json` / `docs/stories/PGD-06.md` changes are prior-phase harness bookkeeping (research/plan-implementation phase mirrors), not implementation-task file changes.
- No `adr-violation`: all five DECISIONS.md entries (D-01..D-05) are honored exactly as specified, including the subtle ones (D-03's no `org_id` filter, D-05's proxy-only frontend scope with no chart/filter component).

## Explicit assessments (items 1-5 from the task)

1. **FR-1/D-01 correctness** — Confirmed correct. `fetch_program_session_series` never filters `member_id IS NULL`; the unfiltered branch is a genuine `GROUP BY` SUM across all member rows. `PGD-06-TC-01` (`test_cross_member_sum_on_same_day_tc01`) seeds two distinct members on the same day and asserts the exact summed total, which would fail under a regression to the story's original (factually wrong) null-filter premise.
2. **FR-6 gate-before-query ordering** — Confirmed structural. In `app/api/overview.py::get_program_session_series`, `program_visibility(...)` then (when `member_id is not None`) `member_in_program_visibility(...)` are both awaited, in sequence, strictly before `fetch_program_session_series(...)` is called — a raised `HTTPException` from either gate short-circuits before the service function is ever reached. `PGD-06-TC-08` proves this with a `before_cursor_execute` query spy scoped to `session_series`-touching SQL, asserting zero matches on the denied path (not merely a 403 status code), plus asserting the `member_view_denied` log fired exactly once and the response body carries no `points`/`period_total_seconds`/`avg_seconds_per_day` keys.
3. **D-02's no-index decision** — Adequate guard. `tests/perf/test_program_session_series_perf.py` seeds 50 members × 100 days (5,000 rows, clearing both TC-17 floors) and asserts, per range (7d/30d/90d) and for the self-filtered path: exactly one `session_series` SELECT (no N+1/fan-out) and wall-clock <2000ms. Both ran successfully (`4 passed` under `pytest -m perf`) at these seeded volumes. This satisfies `.claude/rules/performance-baseline.md`'s "profile, then change" posture — the decision is accepted with a concrete, non-vacuous regression tripwire, not silently ignored.
4. **AF-01 post-triage fix (403 vs 404)** — Agree with the story's own judgment: inapplicable. `.claude/rules/security-baseline.md`'s "404, never 403, for foreign-owned resources" governs per-resource ownership checks (a `_load_owned(id, user_id)` pattern) where a 403 would confirm a resource's existence to a non-owner. Here, `member_in_program_visibility`'s 403 is a persona/authorization decision on an open-aggregate program resource (`program_visibility` already passed for any authenticated session — the program's existence is not gated at all, per D-04/FR-3's no-404 contract) — there is no ownership fact being protected from disclosure. This exactly mirrors AUTH-03's own `member_in_program_visibility` contract and PGD-05's already-shipped, already-reviewed `/team/{member_id}/usage` route, so it is not a novel interpretation introduced by this story.
5. **Test quality** — Confirmed non-vacuous for all three named risk areas: TC-01 asserts the exact summed value (4200), not just 200/non-empty. TC-08 uses a `before_cursor_execute` spy asserting zero query executions, not just the 403 status. TC-16's log assertion is a positive existence check on the `app.api.overview` logger (`program_drilldown`) — the file's own docstring correctly notes this is deliberately self-witnessing against the Alembic `fileConfig(disable_existing_loggers=True)` trap (a negative "no event fired" assertion would pass vacuously if the logger were silently disabled; this positive one fails loudly instead). One minor completeness gap noted as F-1 (LOW, non-blocking) in TC-15's route-level differential assertion.

## Recommendation

PASS. No CRITICAL, HIGH, or MEDIUM findings; one LOW (non-blocking) testability note. Proceed to merge; F-1 may be picked up opportunistically or carried forward, no action required before merge.
