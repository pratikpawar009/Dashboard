# Code Review — feature/BED-05

- Date: 2026-09-09T16:00:00Z
- Mode: story (GATE MODE — report-only; source snapshot f4faa6ab)
- Files reviewed: 12 modified + 4 new (source scope) — `rollup_rebuild.py`, `db.py`, `models/ingestion.py`, `conftest.py`, `prd_8_4_schema.json`, `test_rollup_rebuild_perf.py`, `test_migrations.py`, `test_rollup_rebuild_contract.py`, `test_rollup_rebuild_query_plan.py`, `test_rollup_rebuild_transaction.py`, `docs/requirements/data.md`, `alembic-patterns/SKILL.md`, `migrations/versions/004_rollup_query_indexes.py`, `scripts/generate_rollup_golden_snapshots.py`, `test_rollup_rebuild_concurrency.py`, `test_rollup_rebuild_golden_snapshot.py`
- Verdict: **PASS WITH WARNINGS**

## Executive summary

The SQL-`GROUP BY` rewrite of `rollup_rebuild.py` is careful, well-documented, and internally consistent with its own decision log (D-01–D-06). AC-6 output identity is verified against a real (large, and non-regenerable) golden-snapshot truth model; AC-9's index correction (D-06, ships `ix_usage_events_program_id_covering` instead of the originally-planned `ix_usage_events_ts`) is evidence-driven and the model/migration/fixture triangle required by this repo's schema-diff gates is correctly kept in sync (AF-09). AC-2/AC-3 regression coverage is solid, including a genuine git-blob byte-identity check for the two frozen call sites.

🟢 **Strengths**: order-independence audit (D-01) is real per-function analysis, not hand-waving; the AC-1 concurrency test proves genuine overlap (not just "zero errors") via a log-interval vacuous-pass guard; the index decision (D-06) is reversed on measured `EXPLAIN ANALYZE` evidence rather than shipped as originally planned; `contention_wait_ms` is correctly excluded from the frozen `RebuildResult` and never carries PII.

⚠️ **Warnings**: the org-singleton `ON CONFLICT DO UPDATE` mechanism's correctness claim ("converges regardless of commit order," D-01/DATA-DESIGN §5) is proven only for a *static* `usage_events` read-set — which is what AC-1's own test holds — not for the genuinely moving-target case of concurrent *different-program* ingests each committing new rows during the race window; the `_build_user_sessions` → `func.min(user)` translation leans on a schema-unenforced invariant with no violation-detection test; the golden-snapshot/concurrency/perf fixtures universally use one event per session, which both inflates the checked-in fixture size (~49MB) and leaves multi-row session aggregation untested at AC-6 scale (though covered at small scale by the unchanged `test_rollup_rebuild_program.py`).

🛑 **Blockers**: none.

## Findings summary

| Severity | Count | Category distribution |
|----------|-------|------------------------|
| CRITICAL | 0 | — |
| HIGH | 1 | integration (1) |
| MEDIUM | 2 | testability (2) |
| LOW | 3 | pattern-consistency (1), scope-creep (2) |

## Detailed findings

### HIGH

#### F-1 — integration: org-singleton `ON CONFLICT DO UPDATE` convergence claim holds only for a static read-set, not for the genuinely concurrent write case AC-1 exists to protect against
- Category: integration points
- Path: `services/api/app/services/rollup_rebuild.py:575-666` (`_upsert_org_summary`, `_upsert_month_series`, `rebuild_org_rollups`); claim recorded at `docs/features/BED-05/DECISIONS.md` D-01 and `DATA-DESIGN.md` §5 ("all four converge on the identical final row set regardless of which commits first")
- Description: D-01's order-independence audit correctly proves the nine aggregate *functions* are commutative — i.e., given one fixed, fully-settled `usage_events` content, every concurrent writer computes the same aggregate. That is a necessary but not sufficient condition for the stronger claim D-01/DATA-DESIGN §5 actually make. Each org-scope write is read-then-blind-overwrite: the aggregate is computed in Python (a dict of plain values), then applied via `ON CONFLICT DO UPDATE SET col = :value` — Postgres never recomputes the aggregate at commit time, it only serializes the *write*. So if transaction A's `SELECT` runs before transaction B's `usage_events` commit, but A's `UPSERT` itself commits *after* B's own (correct, complete) org-rebuild commit, A's stale aggregate silently overwrites B's fresher one — with no exception, no log signal, and no way to distinguish this from a normal write. `contention_wait_ms` measures lock-wait time, not staleness, so it would not surface this either. This is exactly AC-1's own real-world motivation ("four concurrent ingest-triggered rebuilds on four distinct programs") but the AC-1 test (`test_rollup_rebuild_concurrency.py`) cannot exercise it: it seeds all `usage_events` once, *before* the concurrent phase starts (step 1), then races only the org-rebuild *writes* against that now-static data (steps 4-5) — by construction, every one of the four org-rebuild SELECTs sees identical, complete data, so all four aggregates are trivially identical regardless of commit order. In production, per D-05's own caller ordering, each program's ingest commits its *own* `usage_events` write immediately before triggering its own org rebuild — so a genuinely overlapping ingest for a *different* program can still be mid-flight (uncommitted) when this program's org-rebuild SELECT runs. This does not corrupt data permanently — the next ingest anywhere in the system re-derives fully and self-heals — and it replaces a *louder* failure mode (the shipped version's IntegrityError/500, also silently divergent per D-05's own accepted risk) with a *quieter* one, which is arguably a net improvement, not a regression. But the "converges on the identical final row set" framing in D-01/DATA-DESIGN §5 overstates what's actually guaranteed, and this residual risk is undocumented anywhere (research risk register, DECISIONS.md, or a carry-forward).
- Suggested fix: not a merge-blocker as scoped — recommend documenting this precisely as a residual/accepted risk (parallel to AF-08's treatment) in `DECISIONS.md`, correcting D-01/DATA-DESIGN §5's wording from "converges regardless of commit order" to "converges once no write to the affected scope is in flight, self-healing on the next rebuild." If stronger guarantees are wanted later, the fix is to serialize the org-scope read+write critical section (e.g., `pg_advisory_xact_lock` scoped only around the three org-scope statements, not the whole transaction) so the last-to-commit writer is guaranteed to have read the state left by every prior lock-holder — closing exactly the gap the fallback mechanism existed for, which D-01 dismissed for a different (also-true, but insufficient) reason.

## Answers to the specific questions raised

1. **Is the golden-snapshot test sufficient for AC-6?** Yes, for what it is designed to check (SQL-vs-Python aggregation output identity over a fixed, already-committed dataset) — but it is not the *only* safety net, and shouldn't be read as one: the unchanged, pre-existing `test_rollup_rebuild_program.py`/`test_rollup_rebuild_idempotency.py` suite already exercises multi-row-per-session aggregation (`sess-1`/`sess-2`/`sess-3` each spanning 4-5 events) and still runs against the rewritten implementation. The golden-snapshot/concurrency/perf fixtures (all new, all one-event-per-session) do *not* exercise that case at scale — see F-3. Neither the golden-snapshot test nor any other test can catch F-1's concurrency/staleness gap, because it's a cross-transaction timing property, not an output-shape property — a golden-snapshot comparison, however scaled, is structurally the wrong tool for it.
2. **Is `session_id` → single `user` schema-enforced, or only test-data-enforced?** Confirmed by reading `services/api/app/models/ingestion.py:27-30`: only test-data-enforced. The one relevant constraint is `UniqueConstraint(program_id, session_id, cmd_ts)` — nothing ties `session_id` to a single `user`. See F-2.
3. **Is the explicit `'UTC'` `date_trunc` zone sound?** Yes in practice for this deployment (`docker-compose.yml`'s `postgres:16` service sets no `TZ`, so the container defaults to UTC, matching what both the golden-snapshot generator and every test run against) — see F-4 for the one loose end (undocumented assumption + inconsistency with `personal_usage.py`'s un-zoned 2-arg call).
4. **Are the ~49MB fixtures reasonable?** The *decision* to durably check them in is sound and well-argued (the source-of-truth pre-rewrite code is deleted by this same diff, so they cannot be regenerated later) — but the *size* is inflated by an avoidable data-shape choice. See F-3.
5. **Can `contention_wait_ms` be negative/wrong, or leak PII?** No to both, verified by reading `_upsert_org_summary`/`_upsert_month_series` (`rollup_rebuild.py:575-628`): timed with `time.perf_counter()` (monotonic, start-then-immediately-after — cannot go negative), bounded above by the new 5000ms statement timeout (`db.py`), and the dicts/log `extra={}` passed around carry only aggregated counts/sums, never `UsageEvent.user`.

### MEDIUM

#### F-2 — testability: `func.min(UsageEvent.user)` depends on an unenforced 1:1 session→user invariant, with no test for its violation
- Category: testability
- Path: `services/api/app/services/rollup_rebuild.py:373-414` (`_build_user_sessions`); schema at `services/api/app/models/ingestion.py:27-30`
- Description: D-01 and the code's own docstring correctly disclose that `func.min(user)` is safe "only because `session_id` maps 1:1 to a single `user` by construction" — but this is a data-quality convention, not a database invariant: no `CHECK`, no composite unique/foreign key ties `session_id` to one `user`. If that convention is ever violated upstream (a bug, or two users somehow sharing a `session_id`), the shipped Python version picked an arbitrary (order-dependent, actually non-deterministic across identical re-runs, since the original `SELECT` carried no `ORDER BY`) `user`; the rewrite now picks a *deterministic* one (`MIN`) — plausible-looking output with no signal that the invariant broke. No test in this diff (or in the existing suite) exercises a session_id spanning >1 distinct user.
- Suggested fix: not blocking. Cheap, high-value addition: a lightweight data-quality check (either a one-off query in a follow-up story, or a debug-level log line when `COUNT(DISTINCT user)` per `session_id` > 1 is detected during a rebuild) so an invariant violation surfaces instead of silently resolving to the alphabetically-smallest user. Record the schema gap explicitly in `DATA-DESIGN.md` rather than leaving it implied by the docstring alone.

#### F-3 — testability / reusability: golden-snapshot fixtures are needlessly large and structurally unable to test multi-row session aggregation at scale
- Category: testability
- Path: `services/api/scripts/generate_rollup_golden_snapshots.py:32` (`session_id` = `f"sess-{i}"`, one session per row), reused verbatim by `tests/unit/test_rollup_rebuild_golden_snapshot.py:132` and `tests/unit/test_rollup_rebuild_concurrency.py:102`
- Description: every new BED-05 fixture (golden-snapshot generator, AC-6 comparison test, AC-1 concurrency test) seeds one `usage_events` row per `session_id`. Two consequences of the same root cause: (a) `user_sessions` — which is `GROUP BY session_id` — degenerates to one row per input row, so it dominates the fixture (≈160,000 of ≈162,600 rows at the 160k size) and is the primary driver of the ~49MB checked-in total (34MB/8.6MB/4.3MB across the three sizes); (b) every `func.sum`/`func.min` aggregate in `_build_user_sessions` is exercised only on singleton groups, where SUM/MIN of one value is definitionally correct — this specific function is the one D-01 flagged as the audit's one interesting case, yet the large-scale AC-6 safety net can't actually exercise its multi-row aggregation path (the *older*, small-scale `test_rollup_rebuild_program.py` does, mitigating but not closing this — see answer to question 1 above).
- Suggested fix: regenerate the golden snapshots with a smaller session-to-event ratio (e.g., ~20-50 events per session, matching a plausible real session length) rather than 1:1. This shrinks `user_sessions`' row count by the same factor (cutting the fixture set by an order of magnitude) and simultaneously closes the multi-row-aggregation coverage gap at the sizes that matter. Not blocking — the current fixtures are durable and correct for what they do test, just avoidably large and narrower than they could be for the same cost.

### LOW

#### F-4 — pattern-consistency: explicit-zone `date_trunc('UTC')` diverges from the existing `personal_usage.py` precedent, assumption undocumented
- Category: pattern-consistency
- Path: `services/api/app/services/rollup_rebuild.py:316,344,533,557` vs. `services/api/app/services/personal_usage.py:134` (`func.date_trunc("day", UserSessions.started_at)`, no zone argument)
- Description: the new code's explicit 3-argument `date_trunc(..., 'UTC')` is a defensible, arguably *better* choice (deterministic regardless of session `TimeZone` GUC) and is verified sound for this project's actual deployment (`docker-compose.yml`'s `postgres:16` sets no `TZ`, defaulting the container to UTC — matching every environment the golden snapshots and tests run against). But it introduces a second convention for the same conceptual operation without noting the divergence, and the "Postgres session TimeZone is UTC" assumption this whole rewrite leans on is nowhere written down (not in `DECISIONS.md`, not in `DATA-DESIGN.md`).
- Suggested fix: not blocking. Add one line to `DECISIONS.md`/`DATA-DESIGN.md` naming the "Postgres TimeZone GUC assumed UTC (docker-compose sets no override)" assumption explicitly, and consider a follow-up to align `personal_usage.py`'s call to the same explicit-zone form for consistency.

#### F-5 — scope-creep: `prd_8_4_schema.json` picked up two unrelated string re-encodings alongside the intended constraint addition
- Category: scope-creep
- Path: `services/api/tests/fixtures/prd_8_4_schema.json` (org_summary_rollup `constraints` note and two `as_of_timestamp` notes — `—`/`§` escapes rewritten to literal `—`/`§`)
- Source: `tasks.json` F-13c (scoped to adding the new `index(program_id)` constraint line only)
- Description: three unrelated JSON string values were re-serialized (escape sequences replaced by literal Unicode characters) with no change in meaning — almost certainly an incidental side effect of whatever tool/editor touched the file, not a deliberate edit. Zero behavioral impact (same characters, different encoding) and the file's own tests don't compare raw bytes.
- Suggested fix: none required; harmless. Worth a quick `git diff` glance before commit on generated/fixture JSON to catch this class of incidental re-encoding in future.

#### F-6 — scope-creep: `docs/activity/activity.jsonl` mutates several pre-existing, unrelated historical rows rather than only appending
- Category: scope-creep
- Path: `docs/activity/activity.jsonl` (rows for an unrelated `/model` command, and two `AUTH-01`/`AUTH-03` `/arh-implement` entries — `duration_s`, `outcome`, `intervention_count`, `files_created`/`lines_added` all changed on already-recorded rows, alongside legitimate new BED-05/ING-02/SHP-02/AUTH-06 appends)
- Description: not part of BED-05's own source changes, but present in this diff. This dashboard's whole purpose is trustworthy SDLC activity monitoring, so an activity-log mechanism that rewrites already-committed historical rows (not just appends) is worth flagging even though it's clearly a harness/hook-level artifact rather than anything BED-05's implementation touched directly.
- Suggested fix: not blocking for BED-05. Carry forward: investigate `.claude/hooks/harness-activity.mjs` (or whatever process writes this file) for why historical rows for other features are being rewritten rather than left immutable once recorded.

## What went well

- D-01's per-function order-independence audit is genuine analysis (9 functions individually characterized), not an assumption.
- D-06 reverses the originally-planned index (`ix_usage_events_ts`) on real `EXPLAIN ANALYZE` evidence rather than shipping the plan-time guess, and correctly identifies *why* no expression index could ever serve the 3-arg `date_trunc` (STABLE, not IMMUTABLE).
- `test_rollup_rebuild_concurrency.py`'s vacuous-pass guard (proving genuine wall-clock overlap from log intervals, not just "zero errors") is a well-designed defense against an accidentally-serialized concurrency test silently passing for the wrong reason.
- AC-3's call-site-frozen check is a real git-blob byte comparison against the pre-BED-05 merge-base, not an import-only smoke test.
- The model/migration/fixture triangle for the new index (`ingestion.py` `__table_args__`, migration 004, `prd_8_4_schema.json`) is correctly kept in sync after AF-09's triage, closing both enforcing gates (`TestSchemaDiffGate`, `TestFixtureDrivenTableConstraints`).
- `contention_wait_ms` correctly stays log-only, never touching the frozen `RebuildResult` contract, and carries no PII.

## Recommendation

**PASS WITH WARNINGS.** One HIGH finding (F-1) — a real, previously-undocumented residual risk in the org-singleton concurrency mechanism's correctness claim, not a defect in what was actually asked for (AC-1's own literal wording, and its test, are satisfied). Recommend: correct D-01/DATA-DESIGN §5's overclaim, record the residual risk explicitly, and proceed — this does not warrant a fix pass before merge given the self-healing, likely-net-improvement-over-shipped character of the gap. F-2/F-3 are worth a low-cost follow-up but are not blocking. F-4/F-5/F-6 are informational.

On AF-08 (already triaged/deferred, not re-raised here as a new finding): agree with the existing "carry forward, don't block" call for BED-05 itself — the measured 3,645ms p95 at 40k in-program rows is a known, accepted, well-documented scoping limit, and blocking this PR would not fix it (the fix is a separate architectural decision — incremental rebuild or moving out of the request path — that the story correctly declines to make unilaterally). The sharper implication is for **ING-02**: it cannot ship as scoped without its own resolution of this, since 3.6s alone exceeds its stated ≤3s end-to-end ceiling before validation/upsert/HTTP overhead is even added. Recommend this be surfaced as a blocking dependency note on ING-02's own plan, not reopened here.
