# Requirement: rollup rebuild must survive real ingest volume and concurrent programs

## Problem

`app/services/rollup_rebuild.py` (BED-03) works correctly and is shipped. It was built and measured
against a **seeded, empty-table** scenario — 5000 events into a fresh database, rebuilt in under 2s.
That is the only load it has ever seen, because **nothing writes `usage_events` yet**.

ING-02 is the story that changes this. It is the activity-ingest endpoint, and AC-1 requires it to
call `rebuild_program_rollups(program_id)` and `rebuild_org_rollups()` synchronously inside the
request, within a p95 ≤ 3s budget for a 5000-row batch.

That budget is not achievable against the shipped rebuild, and the failure is not a slow path — one
of the two defects is a hard 500. Both were **reproduced live** against Postgres during
`/arh-research ING-02` (report: `docs/research/ING-02.md`, risks #1–#3), not inferred:

| total rows | in program | upsert | program rebuild | org rebuild | **total** |
|---:|---:|---:|---:|---:|---:|
| 20k | 5k | 1,829 ms | 588 ms | 417 ms | **2,834 ms** |
| 40k | 10k | 1,789 ms | 1,131 ms | 802 ms | **3,722 ms** |
| 160k | 40k | 1,864 ms | 4,805 ms | 3,864 ms | **10,533 ms** |

94% of budget on the *first* 5000-row push; over budget on the second. The measurement excludes
HTTP, JSON parsing and 5000 Pydantic validations, so real requests are worse.

The root cause is a **category error in the NFR, not slow code**: the budget is indexed to *batch
size*, but rebuild cost is driven by *accumulated table size*. Every rebuild re-reads the whole
history. ING-02 is precisely the thing that makes that history grow, so the budget degrades on every
push, forever.

## Decision (already made — do not re-litigate)

`/arh-clarify ING-02` round 1, Q-03, answered 2026-09-09 by Pratik Pawar:

> **A new story owns the rollup fix; ING-02 depends on it.**

ING-02 does **not** edit `rollup_rebuild.py`. The standing RTM decision (2026-09-08) that "no
validated story reopens" holds — the same rule that forced ING-10 to create `program_roster` rather
than touch `program_members`. This requirement is that new story's source.

Three further scoping decisions, answered 2026-09-09 by Pratik Pawar:

- **The org rebuild stays in the request path.** It is serialised, not relocated. ING-02's AC-1
  ("rebuild synchronously") stands unchanged, and no staleness semantics need designing. The
  consequence is deliberate and load-bearing: with the cost staying on the critical path, the
  budget can only be met by expectation 2 — see § Sizing.
- **One story, not two.** Concurrency-correctness and rebuild-scaling ship together under one gate.
  Splitting would have unblocked ING-02 sooner, and was declined.
- **Both rebuild functions are in scope** — `rebuild_program_rollups` and `rebuild_org_rollups`.
  The concurrency failure is org-only, but the growth curve hits both (588 ms → 4,805 ms program,
  417 ms → 3,864 ms org), and fixing only the org path leaves ING-02 over budget at volume.

Bundling the fix into ING-02 was considered and rejected: it would put a rewrite of shipped internals
that **every** ingest path depends on into a new-endpoint PR, which is the bundled-refactor pattern
`.claude/rules/surgical-changes.md` forbids. The fix gets its own gate.

## Functional expectations

### 1. Concurrent programs must not fail each other

Reproduced: **2 of 4 concurrent pushes on *distinct* programs** returned
`IntegrityError: duplicate key value violates unique constraint "org_summary_rollup_org_id_key"`.
Every ingest DELETE+INSERTs the same org singleton row, so concurrent rebuilds collide.

This surfaces as a 500. Worse, following the commit-then-rebuild precedent at
`manifest_ingest.py:355`, the losing request leaves `usage_events` **committed with rollups
un-rebuilt behind that 500** — silent data/rollup divergence, not just a failed request.

Two things must come out of this:

- Concurrent rebuilds triggered by different programs must both succeed, **with the org rebuild
  still inside the request** (decided above). Candidate mechanisms: `pg_advisory_xact_lock` around
  the org rebuild, or `ON CONFLICT DO UPDATE` on the org singleton instead of DELETE+INSERT.
  Relocating it out-of-band is **not** an available mitigation here, so serialisation must be cheap
  enough to hold the budget under concurrency, not merely correct.
- **The commit boundary must be defined explicitly** — either one transaction spanning upsert and
  rebuild, or a documented, tested partial-failure response. Today it is neither; it is an accident
  of ordering.

### 2. Rebuild cost must stop scaling with total history — **load-bearing**

This is the expectation the budget now rests on. Because the org rebuild stays synchronous
(decided above), there is no out-of-band escape hatch: if rebuild cost still grows with
history, ING-02 cannot meet p95 ≤ 3s at any volume. **Both** `rebuild_program_rollups` and
`rebuild_org_rollups` are in scope.

`rebuild_org_rollups` (`rollup_rebuild.py:459`) opens with a bare `select(UsageEvent)` at line 470 —
no `WHERE`, no `LIMIT` — materialising the entire table into process memory as ORM objects. That is
a direct `.claude/rules/performance-baseline.md` violation ("no unbounded fan-out reads"), and a
memory-growth risk independent of latency.

Everything these rollups need is expressible as SQL aggregation: `token_series` and `mau_series` are
per-month, and `org_summary_rollup` needs distinct-program counts and sums — all `GROUP BY` work
that should never load a row into Python. `rebuild_program_rollups` has the same shape and the same
growth curve (588 ms → 4,805 ms across the table sizes above).

### 3. An explicit I/O timeout

There is no statement or connection timeout anywhere — `app/core/db.py:17` is a bare
`create_async_engine`. `app/services/freshness.py:32` (BED-04) already flagged this. A rebuild that
degrades should fail on a bound, not hang. `.claude/rules/performance-baseline.md` requires it.

### 4. A performance test that measures the real curve

BED-03's existing budget was measured on an empty table, which is what allowed this to ship
unnoticed. The replacement must measure against a **populated, growing** table and assert against
table size, not batch size — otherwise the same trap re-arms the moment volume arrives.

## Explicitly out of scope

- **The ING-02 endpoint itself.** Auth, validation tiers, the response envelope and the row upsert
  all belong to ING-02.
- **Two defects that live in ING-02's own new code, not here** — recorded so decomposition does not
  pull them in:
  - A 5000-row batch cannot be one INSERT: 22 columns × 5000 = 110,000 bind parameters against
    Postgres' 65,535 ceiling (reproduced: `psycopg.OperationalError`; max 2,978 rows/statement).
    Chunking is ING-02's upsert concern.
  - Two rows sharing `(program_id, session_id, cmd_ts)` **within one batch** raise
    `CardinalityViolation` and abort the whole statement rather than rejecting one row. Pre-upsert
    de-duplication is ING-02's concern.
- **Changing what the rollups compute.** This is about how they are computed, not their output.
  Existing rollup values must be identical before and after, at every table size.
- **The `usage_events` additive migration** for `source` / `copilot_credits` (clarify Q-01) — that
  rides with ING-02.

## Prior art to reuse, not reinvent

- `app/services/rollup_rebuild.py` — the engine being changed. Its D-01 (one transaction per scope)
  and D-05 (unfiltered read) decisions are what this requirement revisits; read `DECISIONS.md` for
  BED-03 before proposing an alternative.
- `app/services/manifest_ingest.py:355` — the commit-then-rebuild ordering precedent whose
  partial-failure behaviour is the hazard in expectation 1.
- `tests/perf/test_persona_resolver_perf.py` and `tests/perf/test_programs_perf.py` — the in-repo
  perf-test convention (plain `perf_counter`, copied `_percentile`, a named budget constant, and a
  failure message that says "do not relax this budget"). Note `_percentile` is now duplicated across
  8 files; a shared `tests/perf/_helpers.py` is an open carry-forward.
- `docs/research/ING-02.md` § Risk register — the full measurements, reproduction steps and
  candidate mitigations for risks #1, #2 and #3.

## Sizing

Expect **L**. One story now carries: an org-singleton concurrency fix, a SQL-aggregate rewrite of
both rebuild paths, an explicit I/O timeout, a defined commit boundary, and a perf test rebuilt
around table size. It is on ING-02's critical path in full — ING-02 stays blocked until all of it
lands, which is the cost of the one-story decision.

Rollup **output must be identical before and after, at every table size.** That invariant is what
makes a rewrite of this size safe to review, and it should be asserted directly rather than implied
by the existing unit tests.

## Open questions for decomposition to resolve

1. **What is the replacement budget, expressed how?** Expectation 4 fixes the *shape* — assert
   against table size, not batch size — but not the number. It needs measuring against a populated
   table once the aggregate rewrite exists, then pinning. ING-02's p95 ≤ 3s end-to-end is the
   ceiling this has to fit inside, alongside validation, upsert and HTTP.
2. **Advisory lock or `ON CONFLICT` for the org singleton?** Both fix the collision. The lock
   serialises whole rebuilds (simpler to reason about, but concurrent pushes then queue);
   `ON CONFLICT DO UPDATE` lets them interleave but needs the rebuild to be genuinely
   order-independent. Worth deciding with a measurement, not a preference.
