# Feature: BED-05 — Rollup rebuild scaling + concurrency safety

## Problem

`rollup_rebuild.py` (BED-03, shipped) rebuilds every rollup table by materialising `usage_events`
into Python objects. It was measured only against an empty-table seed (5,000 rows, <2s) because
nothing writes `usage_events` yet. Measured live against a populated table (`docs/research/ING-02.md`),
cost tracks total table size, not batch size: `rebuild_program_rollups` 588 ms → 4,805 ms and
`rebuild_org_rollups` 417 ms → 3,864 ms across 20k → 160k rows. Because ING-02 keeps the org rebuild
synchronous inside the request (RTM decision, not re-litigated here), this growth curve alone puts
ING-02's p95 ≤ 3s budget out of reach at any real volume. Separately, `org_summary_rollup`'s
`unique(org_id)` singleton DELETE+INSERT collides under concurrent pushes from distinct programs —
reproduced live, 2 of 4 concurrent rebuilds fail with `IntegrityError` on
`org_summary_rollup_org_id_key` — surfacing as a request 500 and, per the shipped
commit-then-rebuild ordering, leaving `usage_events` committed with rollups un-rebuilt behind it.

## Outcome

`rebuild_program_rollups`/`rebuild_org_rollups` derive every rollup row via SQL `GROUP BY`
aggregation, with no per-event ORM materialisation and no `select(UsageEvent)` full-table read. Four
concurrent rebuilds on four distinct programs all succeed with zero `IntegrityError`. A failure after
the DELETEs rolls back that scope completely and the exception reaches the caller. Rebuild queries
fail on an explicit statement/connection timeout instead of hanging. The `rollup-rebuild` contract
and every rollup value are unchanged (byte-identical to the shipped implementation, excluding
generated id/clock columns) at every measured table size. ING-02 becomes buildable against a rebuild
that holds its latency budget at any `usage_events` volume instead of degrading on every push.

## Constraints

- Frozen `rollup-rebuild` contract (`docs/requirements/data.md#rollup-rebuild`): same
  `rebuild_program_rollups`/`rebuild_org_rollups` signatures, same `RebuildResult`, same
  full-re-derive invariant, output identical before/after at every table size (AC-6).
- No call-site edits: `services/api/app/api/ingest.py`,
  `services/api/app/services/manifest_ingest.py:355` (AC-3, ING-10 shipped).
- Org rebuild stays synchronous in the request path — no staleness semantics, no out-of-band
  relocation (RTM decision, taken as given).
- Additive-only Alembic revision (AC-9): index-only, revising `003_program_roster`, no
  column/constraint/data change, downgrade drops exactly what it added; `001_initial_schema.py`
  untouched, no validated story reopened.
- Out of scope, frozen: the ING-02 endpoint itself; 65,535 bind-parameter chunking; intra-batch
  `CardinalityViolation` de-duplication; changing *what* the rollups compute; the `usage_events`
  additive migration for `source`/`copilot_credits`.
- Two recorded deferrals, not open questions — owned by `/arh-plan-implementation`, each bounded
  here and in `docs/stories/BED-05.md` § Decision log:
  - **Replacement budget**: measurement-derived from the rewritten aggregate. Ceiling: the
    rebuild's share of ING-02's p95 ≤ 3s for a 5000-row batch. Shape: asserted against table size
    (never batch size), flat across ≥2 of {20k, 40k, 160k} rows.
  - **Org-singleton mechanism**: `ON CONFLICT DO UPDATE` is the decision of record;
    `pg_advisory_xact_lock` is the named fallback, conditional on the rewritten aggregate proving
    order-independent.

## Solution sketch

Rewrite the aggregation functions behind both rebuild scopes to push `GROUP BY`/`SUM`/`COUNT DISTINCT`
work into SQL rather than materialising `usage_events` rows into Python, reusing the existing
`.group_by()`/`func.*` pattern already in `personal_usage.py`. Keep `_rebuild_transaction`'s atomicity
wrapper and both public signatures untouched. Add an explicit statement/connection timeout to the
shared async engine, resolve the org-singleton collision per the deferred mechanism decision, and add
one additive index-only Alembic revision to support the new query shapes. Replace the perf test's
empty-table constants with a populated, growing-table, table-size-indexed budget assertion. Verify
output identity against golden snapshots captured from the shipped implementation at 20k/40k/160k
rows before the rewrite starts.

## Addressing Research Conditions

- C-1 (Plan-phase gate: Concurrency mechanism design review) — BED-05-FR-2 requires auditing every
  rewritten aggregation function for row-order sensitivity before the org-singleton mechanism is
  finalized; the audit result gates whether `ON CONFLICT DO UPDATE` proceeds or
  `pg_advisory_xact_lock` is substituted (Decision log "Org-singleton mechanism deferral").
- C-2 (Plan-phase gate: Timeout value measurement) — BED-05-FR-3 requires measuring the rewritten
  rebuild under the AC-1 four-program concurrency case before pinning the statement/connection
  timeout, with headroom above that measurement and inside the ≤3s ceiling, validated by a
  preflight pass over existing DB-touching code paths.
- C-3 (Plan-phase gate: Golden-snapshot generation) — BED-05-FR-1 requires generating snapshots
  from the shipped (pre-rewrite) implementation at 20k/40k/160k rows, before the rewrite starts, as
  the AC-6 output-equivalence truth model.
- C-4 (Implementation prerequisite: AC-1 four-program concurrency fixture) — BED-05-FR-4 requires a
  new concurrent-session fixture in `services/api/tests/conftest.py` running four rebuild call
  pairs on four distinct programs against the real test-Postgres; no existing fixture provides
  multi-session concurrency.
- C-5 (Code review gate: Perf test growth-curve assertion) — BED-05-FR-5 requires the rewritten
  perf test to assert duration against table size (not batch size) at ≥2 measured sizes and fail on
  growth-curve regression, replacing the empty-table `EVENT_COUNT=5000`/`BUDGET_SECONDS=2.0`
  constants.

## Scope

- In: SQL-aggregation rewrite of every `_build_*` function backing `rebuild_program_rollups` and
  `rebuild_org_rollups`; org-singleton concurrency fix; explicit engine-level statement/connection
  timeout; one additive index-only Alembic revision; rewritten perf test; golden-snapshot generation
  and comparison at 20k/40k/160k rows; `contention_wait_ms` observability field.
- Out: The ING-02 endpoint itself (auth, validation tiers, response envelope, row upsert); the
  65,535 bind-parameter chunking; intra-batch `CardinalityViolation` de-duplication; changing what
  the rollups compute; the `usage_events` additive migration for `source`/`copilot_credits`;
  call-site edits to `ingest.py`/`manifest_ingest.py:355`; `mau_series` role-breakdown beyond the
  existing all-to-developer bucketing (BED-03 D-03, unchanged).

## Functional requirements

FRs trace 1:1 to story ACs; see `docs/stories/BED-05.md` for canonical wording.
New impl constraints introduced below:

**BED-05-FR-1** — Golden-snapshot truth model  *(extends AC #6 with: generation sequencing)*

Snapshots must be generated from the shipped (pre-rewrite) implementation against seeded
20k/40k/160k-row tables — exporting every rollup-table row/column — before the rewrite begins.
Comparison excludes `id` and the `as_of_timestamp`/`created_at`/`updated_at` clock columns (per
story Decision log).

**BED-05-FR-2** — Order-independence audit gates mechanism selection  *(extends AC #1 with: a
required design gate)*

Each rewritten aggregation function must be audited for row-order sensitivity before `ON CONFLICT
DO UPDATE` is adopted. If any ordering assumption survives the SQL rewrite, the org-singleton
mechanism switches to `pg_advisory_xact_lock` instead.

**BED-05-FR-3** — Timeout value is measurement-derived and preflight-validated  *(extends AC #7
with: sequencing and validation)*

The statement/connection timeout on the shared async engine (`app/core/db.py:17`) is set only
after measuring the rewritten rebuild under AC-1's four-program concurrency, with headroom above
that measurement and within the ≤3s ceiling. A preflight pass over existing DB-touching code paths
(migrations, auth, ingest) must show no new timeout-induced failures before the value ships.

**BED-05-FR-4** — Four-program concurrency test fixture  *(extends AC #1 with: fixture
requirement)*

A new fixture (in or alongside `services/api/tests/conftest.py`) must run four
`rebuild_program_rollups` + `rebuild_org_rollups` call pairs concurrently on four distinct
programs, each on its own `AsyncSession`, against the real test-Postgres — no existing fixture
provides multi-session concurrency.

**BED-05-FR-5** — Perf test replaces empty-table constants with table-size-indexed assertions
*(extends AC #8 with: replacement mechanics)*

`test_rollup_rebuild_perf.py` seeds a populated, growing table at ≥2 of {20k, 40k, 160k} total rows
(reused from `docs/research/ING-02.md`), asserts duration against a named per-size budget constant
(set at plan time), and fails on growth-curve regression. `EVENT_COUNT = 5000` /
`BUDGET_SECONDS = 2.0` are removed.

## Non-functional requirements

- Performance: rebuild duration must stop tracking total `usage_events` size. The replacement
  (budget, table-size) pair is measurement-derived at `/arh-plan-implementation` — no number is
  pinned here (Decision log "Budget deferral") — bounded by (a) ceiling: rebuild's share of
  ING-02's p95 ≤ 3s for a 5000-row batch (sourced, ING-02 NFR); (b) shape: table-size-indexed, flat
  across ≥2 of {20k, 40k, 160k} rows, never batch-size-indexed.
- Performance: org-singleton serialisation wait (`contention_wait_ms`) must fit inside the same
  budget under the AC-1 four-program case. Mechanism is `ON CONFLICT DO UPDATE` (decision of
  record) or `pg_advisory_xact_lock` (named fallback), confirmed at plan time per Decision log
  "Org-singleton mechanism deferral".
- Per `.claude/rules/performance-baseline.md`: no unbounded fan-out reads — closes the bare
  `select(UsageEvent)` violation at `rollup_rebuild.py:470`; I/O has explicit timeouts (AC-7).
- Security: Per `.claude/rules/security-baseline.md`: applies to all changed code in scope. No new
  route, no new caller (AC-3) — both functions stay reachable only from
  ingest-token-authenticated write paths. `usage_events.user` (raw git email, PII) must stay out of
  logs; `rollup_rebuild_completed` stays identifier-free.
- Accessibility: N/A — backend service functions, no UI surface (`design: n/a` legitimate; BED has
  no epic in `docs/design/schema.json`).
- Observability: `rollup_rebuild_completed` retains `scope`, `program_id`, `duration_ms`,
  `event_count` (frozen contract) plus adds `contention_wait_ms` (int, 0 when uncontended) — time
  spent waiting on the org-singleton serialisation mechanism, needed because the in-request org
  rebuild puts that wait inside ING-02's p95 (Decision log, logged assumption).

## Visual spec

Not applicable — `integrations.design = none` for this story. BED has no epic in
`docs/design/schema.json`; backend / API / data feature.

## Rollout plan

- **Strategy**: bang-bang — internal rewrite behind a frozen, unchanged contract; no caller edits,
  no new route, safe to deploy in one pass.
- **Feature flag**: none.
- **Backout plan**: revert the `rollup_rebuild.py` rewrite, the engine-timeout change, and the
  additive index migration's downgrade in one PR revert; `usage_events` and existing rollup tables
  are unaffected (no data migration in scope).
- **Success signal**: AC-6 golden-snapshot comparison passes at all three measured sizes; AC-1
  four-program concurrency test shows zero `IntegrityError`; perf test shows flat (non-growing)
  duration across ≥2 table sizes.

## Documentation requirements

- **README updates**: none — no new runnable surface, route, or CLI; `rollup-rebuild` contract
  shape is unchanged.
- **Runbook**: none.
- **API reference**: none — no route change.
- **Inline code comments**: `app/services/rollup_rebuild.py` — document the SQL `GROUP BY` rewrite
  per aggregation function, including the order-independence audit finding (FR-2) and
  `contention_wait_ms` semantics; `app/core/db.py` — document the timeout value's provenance
  (measured, not guessed) and its headroom margin.
- **Examples / how-to**: none.
- The rollup module's own `DECISIONS.md` must record the caller-ordering write-up required by AC-3
  (per `rollup-rebuild`'s `commit_boundary_note`).

## Open questions

None.

Decisions logged in `docs/stories/BED-05.md` § Decision log.

## Approvals

| Role | Approver | Date | Verdict |
|---|---|---|---|
| Product Owner / BA | Pratik Pawar | 2026-09-09 | APPROVE |
| Designer | — | 2026-09-09 | N/A — backend-only, `design_mode = none`, no `DESIGN.md` produced |

Product Gate passed at `/arh-plan-requirements` Phase 4, verdict given by the approver in
response to the gate checklist. Checklist evidence at approval time:

- 5/5 research conditions addressed with concrete mitigations (§ Addressing Research Conditions).
- 0 unresolved `[NEEDS CLARIFICATION]` markers; 0 open questions. The two deferred items
  (replacement rebuild budget; org-singleton mechanism) are recorded deferrals with stated bounds
  and `/arh-plan-implementation` as owner — not open questions.
- No-placeholder check clean.
- Every test case carries a `requirement_id` resolving to a real id — `BED-05-TC-01` → `BED-05-AC-1`,
  `BED-05-TC-02` → `BED-05-AC-8`.
- **Coverage audit does NOT pass, and was approved with the gap accepted.** The test-case manifest
  was capped at 2 cases by explicit instruction, leaving 10 uncovered ids: `BED-05-AC-2`,
  `BED-05-AC-3`, `BED-05-AC-6`, `BED-05-AC-7`, `BED-05-AC-9`, `BED-05-FR-1`, `BED-05-FR-2`,
  `BED-05-FR-3`, `BED-05-NFR-security`, `BED-05-NFR-accessibility`. Most is scope, not omission:
  AC-6/AC-7 are unit-scoped per the story's Test mapping and this manifest is behavioural-only by
  design; AC-2/AC-3/AC-9 and FR-1/2/3 belong in `tasks.json` as unit/contract tasks;
  `NFR-accessibility` is genuinely N/A. **The one substantive consequence carried forward: research
  risk #1 — output-identity divergence at AC-6, rated HIGH — has no behavioural test guarding it and
  relies entirely on unit-level golden-snapshot coverage created during implementation.**
- Tracker subtask: `pratikpawar009/Dashboard#258` (PRD). Research subtask:
  `pratikpawar009/Dashboard#256`.
