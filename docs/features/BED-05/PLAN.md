# PLAN: BED-05 — Rollup rebuild scaling + concurrency safety

Status: Complete

## 1. Architecture Decisions

Technical decisions are recorded in `DECISIONS.md` (this feature's decision log). Five entries, none promoted to a full ADR (all `blast:feature`/`blast:service`, all `rev:mechanical`): D-01 (order-independence audit of all 9 `_build_*` functions confirms `ON CONFLICT DO UPDATE` for the org-scope write path — no `pg_advisory_xact_lock` fallback needed; settles research condition C-1), D-02 (replacement rebuild budget + engine timeout are set by a measure-then-pin task sequence — T-06 measures, T-07 pins — not invented in this plan), D-03 (the timeout is a hardcoded module constant in `app/core/db.py`, not a new `Settings`/env-var field, since no NFR asks for per-environment tuning and the PRD declares no doc changes), D-04 (the additive index-only Alembic revision adds `ix_usage_events_ts`), D-05 (the AC-3 caller-ordering write-up ING-02 must implement, recorded here per the frozen `rollup-rebuild` contract's `commit_boundary_note`).

## 2. File and Module Plan

File plan (`F-NN` → path/action) is maintained in `tasks.json` `file_plan`. 15 entries: 4 create, 2 generate (golden-snapshot fixtures), 9 modify. No new production module is created — every `create` entry is either a one-off script (`F-01`, leaf), generated test-fixture data (`F-02`/`F-03`/`F-04`, leaf), a new test file (`F-09`/`F-10`, leaf per `plan-validation`'s wiring exception), or a self-chaining Alembic revision (`F-13`, discovered via its own `down_revision`, no separate registry file — matching the `002`/`003` precedent).

### Module hierarchy

```
app/services/
└── rollup_rebuild.py                                   (modified — BED-03 shipped)
    - input:  AsyncSession (injected, never self-constructed — unchanged), program_id: str (program scope only)
    - output: RebuildResult (unchanged); full-derived rows in the 10 rollup tables
    - public: rebuild_program_rollups(session, program_id) -> RebuildResult   (signature frozen)
              rebuild_org_rollups(session) -> RebuildResult                   (signature frozen)
    - internals (rewritten, D-01):
        program scope (unchanged write path, DELETE WHERE program_id=:pid + INSERT):
          _build_program_summary, _build_program_commands, _build_program_members,
          _build_session_series, _build_program_token_series -> SQLAlchemy .group_by()/func.*
          _build_user_sessions -> func.min(UsageEvent.user) grouped by session_id
              (replaces the first-occurrence group[0].user pick — D-01 audit)
        org scope (changed write path):
          _build_org_summary -> INSERT ... ON CONFLICT (org_id) DO UPDATE
          _build_token_series, _build_mau_series -> DELETE WHERE org_id=:oid AND month
              NOT IN (:computed_months), then INSERT ... ON CONFLICT (org_id, month) DO UPDATE
        event_count now sourced from SELECT COUNT(*), not len(events)
        contention_wait_ms timed around each org-scope ON CONFLICT statement, added to the
              rollup_rebuild_completed extra={} dict (new field, log-only, no new column)

app/core/
└── db.py                                               (modified — BED-03 shipped)
    - input:  settings.database_url (unchanged)
    - output: process-wide async engine + session factory, now with an explicit
              statement_timeout/connection timeout
    - public: engine, SessionLocal, get_db() — signatures unchanged; new private module
              constants _STATEMENT_TIMEOUT_MS/_CONNECTION_TIMEOUT_S (D-03), values pinned
              by T-07 from T-06's measurement (D-02)

migrations/versions/
└── 004_rollup_query_indexes.py                          (new — additive, index-only, D-04)
    - input:  none (DDL only)
    - output: ix_usage_events_ts index
    - public: upgrade()/downgrade() — Alembic-discovered via its own down_revision="003_program_roster",
              no separate registration file (matching 002_/003_ precedent)

services/api/scripts/
└── generate_rollup_golden_snapshots.py                  (new — one-off script, mint_ingest_token.py precedent)
    - input:  a live/disposable Postgres instance, seeded usage_events at 20k/40k/160k rows
    - output: tests/fixtures/rollup_golden_{20k,40k,160k}.json (checked-in test fixtures)
    - public: __main__ entry point only, no importable API — must run against the SHIPPED
              (pre-rewrite) rollup_rebuild.py, before T-03 lands

tests/ (existing files unless noted "new")
├── conftest.py                                            (modified — four-program concurrent-session fixture)
├── unit/test_rollup_rebuild_golden_snapshot.py             (new — AC-6 comparison against the fixtures above)
├── unit/test_rollup_rebuild_concurrency.py                 (new — AC-1 / BED-05-TC-01)
├── unit/test_rollup_rebuild_transaction.py                 (modified — AC-2 monkeypatch retarget)
├── unit/test_rollup_rebuild_contract.py                    (modified — AC-3 call-site regression)
├── unit/test_rollup_rebuild_query_plan.py                  (modified — D-05 invariant superseded)
├── test_migrations.py                                      (modified — AC-9 targeted index round-trip)
└── perf/test_rollup_rebuild_perf.py                        (modified — AC-8 table-size-indexed budgets)
```

No navigation/routing map — backend-only service-function story, no HTTP route added (Security NFR unchanged from BED-03: no route consumes these functions in this story either).

## 3. Module Hierarchy

See the tree in §2. No new production module is created; `rollup_rebuild.py` and `db.py` are both existing (BED-03-shipped) files being rewritten internally, so no entry-registration wiring changes — `app/main.py`'s existing module-level `engine` import (BED-03 D-02) and `app/services/__init__.py`'s existing barrel export (BED-03 D-04-adjacent wiring) already cover both. `migrations/versions/004_rollup_query_indexes.py` is a new file but self-registers into the Alembic chain via its own `down_revision = "003_program_roster"` field — no separate router/registry file needs editing (same shape `002_personal_usage_indexes.py`/`003_program_roster.py` already established). `generate_rollup_golden_snapshots.py` and every new test file are leaves (script / test), per `plan-validation`'s wiring exception — none needs an entry-registration site.

## 4. State and Data Management

State & data design is maintained in `DATA-DESIGN.md`.

## 5. Task Breakdown

Task DAG + live status is maintained in `tasks.json` `tasks`. Execution order derives from `predecessors`; parallelism derives from the DAG. 13 tasks (T-01..T-13): 5 S, 5 M, 3 L. Every `file_plan` entry (F-01..F-15) is covered by exactly one task; no two DAG-independent tasks share a file (verified programmatically — zero write conflicts).

**Ordering constraint (mandatory, not advisory)**: T-01 (golden-snapshot generation, C-3) has no predecessors and MUST be the first task committed — it captures the AC-6 truth model from the shipped, pre-rewrite implementation. T-03 (the SQL-aggregation rewrite) depends on T-01 for exactly this reason: once T-03 lands, the pre-rewrite behaviour is gone and AC-6 becomes unverifiable from that point forward. Every other task that touches `rollup_rebuild.py`'s test surface (T-09, T-11, T-13) or measures its performance (T-06, and transitively T-07/T-08) depends on T-03.

## 6. Carry-Forward Risks and Conditions

Risks from `docs/research/BED-05.md` § Risk register (`R-01`..`R-10`, matching that doc's numbered order). 9 of 10 are addressed by tasks; `R-09` (LOW) is accepted, per research's own framing that it is not this story's concern.

### Risks addressed by tasks

| Risk id | Severity | Addressed by |
|---------|----------|--------------|
| R-01 | HIGH | T-01, T-09 |
| R-02 | HIGH | T-03, T-13 |
| R-03 | HIGH | T-06, T-07 |
| R-04 | MED | T-03, T-06, T-10 |
| R-05 | MED | T-03 |
| R-06 | MED | T-08 |
| R-07 | MED | T-04, T-05 |
| R-08 | LOW | T-07 |
| R-10 | LOW | T-02, T-10 |

### Risks accepted (carry-forward)

| Risk id | Severity | Rationale |
|---------|----------|-----------|
| R-09 | LOW | `app/main.py:78-88`'s "will be registered by ING-02" comment about the unregistered `app/api/ingest.py` stub stays as-is — BED-05 touches neither file (AC-3 scope boundary: no call-site edits) and research itself flags this as ING-02's concern, not BED-05's. Revisit when ING-02 lands or is confirmed deferred beyond BED-05. |

### Conditions for GO (research_verdict GO-WITH-CONDITIONS)

| Cond | Condition (verbatim) | Addressed by |
|------|----------------------|--------------|
| C-1 | Plan-phase gate: Concurrency mechanism design review — audit each `_build_*` function for ordering assumptions before `ON CONFLICT DO UPDATE` is adopted. | Settled in `DECISIONS.md` D-01 (this planning pass's audit; see § below for the per-function result); implemented by T-03 |
| C-2 | Plan-phase gate: Timeout value measurement — measure the rewritten rebuild under AC-1 four-program concurrency; set timeout with headroom, validated by preflight. | T-06 (measure), T-07 (pin + preflight) |
| C-3 | Plan-phase gate: Golden-snapshot generation — run the shipped impl against seeded 20k/40k/160k tables; export every rollup table row to JSON; implement comparison unit test. | T-01 (generate), T-09 (compare) |
| C-4 | Implementation prerequisite: AC-1 four-program concurrency fixture in `tests/conftest.py`. | T-02 |
| C-5 | Code review gate: Perf test growth-curve assertion — duration flat vs. table size, ≥2 sizes, fails on regression. | T-08 |

### Order-independence audit (C-1, resolved during this planning pass)

Per-function finding (full detail in `DECISIONS.md` D-01):

| Function | Aggregate shape | Order-dependent? |
|---|---|---|
| `_build_program_summary` | `sum`/`len`/`len({set})` | No |
| `_build_program_commands` | `len`/`min`/`max` per group | No |
| `_build_program_members` | `len({set})`/`sum`/`max` per group | No |
| `_build_session_series` | `sum` per group | No |
| `_build_program_token_series` | `sum` per group | No |
| `_build_user_sessions` | `group[0].user` (first-occurrence shape) | **In code shape, yes — flagged.** Order-independent in practice only because `session_id` maps 1:1 to a single `user`; rewrite must use `func.min(user)`, an explicit deterministic aggregate, not an arbitrary pick, so the SQL result is provably (not accidentally) order-independent. |
| `_build_org_summary` | `sum`/`len({set})` | No |
| `_build_token_series` | `sum` per group | No |
| `_build_mau_series` | `len({set})` per group | No |

**Conclusion**: no function has a genuine order-dependent *result*. `ON CONFLICT DO UPDATE` proceeds as the org-singleton mechanism (decision of record confirmed); `pg_advisory_xact_lock` is not needed.

### Cross-Feature Dependency Notes

`ING-02` is blocked on this story in full (RTM Decisions 2026-09-09) — it consumes `rollup-rebuild` unchanged and implements the caller ordering `DECISIONS.md` D-05 writes down. No other in-flight feature shares a file with this plan.

## 7. Test Strategy

| Layer | Test path | TCs / ACs covered | Notes |
|-------|-----------|--------------------|-------|
| Unit | `services/api/tests/unit/test_rollup_rebuild_golden_snapshot.py` | BED-05-AC-6, FR-1 | New (T-09). Load-bearing: research risk #1 (HIGH, output-identity divergence) has no behavioural TC — this unit coverage is the only guard. |
| Unit | `services/api/tests/unit/test_rollup_rebuild_transaction.py` | BED-05-AC-2 | Modified (T-11); retargets the existing TC-10 injected-failure monkeypatch, same full-rollback guarantee. |
| Unit | `services/api/tests/unit/test_rollup_rebuild_contract.py` | BED-05-AC-3 | Modified (T-12); call-site-unchanged + `DECISIONS.md` write-up assertion. |
| Unit | `services/api/tests/unit/test_rollup_rebuild_query_plan.py` | BED-05-AC-4, AC-5 | Modified (T-13); supersedes BED-03 D-05's "exactly 1 SELECT" invariant with a bounded-query-count/no-full-materialisation assertion. |
| Contract | `services/api/tests/test_migrations.py` | BED-05-AC-9 | Modified (T-05); targeted index presence/absence round-trip for revision `004`, in addition to the existing generic full-chain tests. |
| Integration | `services/api/tests/unit/test_rollup_rebuild_concurrency.py` | BED-05-TC-01 (AC-1, FR-4) | New (T-10). Lives under `tests/unit/` matching this codebase's existing convention for real-Postgres rollup_rebuild tests — no `tests/integration/` directory exists (`test_integration:` is empty in `project-commands.yaml`), so this does not introduce one. |
| Performance | `services/api/tests/perf/test_rollup_rebuild_perf.py` | BED-05-TC-02 (AC-8, FR-5) | Modified (T-08). No new runner — plain `pytest`/`time.perf_counter()`, matching the existing `tests/perf/` convention; no k6/locust/separate perf tool is declared in `harness.yaml` or needed here. |
| Security | (folded into contract test above) | BED-05-NFR-security | No new route/caller; `usage_events.user` stays out of logs (T-03's inline audit, existing TC-16 in `test_rollup_rebuild_contract.py` unaffected). |

**Runner-setup dimension — N/A, no new runner needed**: `harness.yaml` declares `pytest` as the only backend test runner; this story's one `performance`-typed TC (`BED-05-TC-02`) and one `integration`-typed TC (`BED-05-TC-01`) both run through the already-installed, already-configured `pytest` (+ `pytest-asyncio`, + the real test-Postgres `migrated_db`/`test_session`/`test_engine` fixtures) — the same mechanism every existing `tests/perf/*.py` and `tests/unit/test_rollup_rebuild_*.py` file already uses. No contract-typed TC exists.

**Docs dimension — N/A, no trigger fires**: no new runnable surface (T1), no new HTTP route (T2), no new env var (T3 — D-03 deliberately keeps the timeout a hardcoded constant, not an env var), no new service/port (T4). Matches the PRD's own "Documentation requirements: README updates: none."

**Config drift dimension — N/A, no trigger fires**: no new runtime dependency (C1 — `sqlalchemy.dialects.postgresql.insert` is already imported elsewhere in this codebase; SQLAlchemy `func`/`.group_by()` are already used in `personal_usage.py`), no new service (C2), no new port (C3).

Coverage note: `BED-05-AC-2`, `BED-05-AC-3`, `BED-05-AC-9`, `BED-05-FR-1`, `BED-05-FR-2`, `BED-05-FR-3` — the ids the PRD explicitly assigned to `tasks.json` as unit/contract work rather than the capped 2-TC behavioural manifest — are covered above by T-11, T-12, T-05/T-04, T-01/T-09, T-03, T-06/T-07 respectively. `BED-05-NFR-accessibility` stays N/A (backend-only, no UI surface, `design: n/a` legitimate).

### Plan validation rounds

| Round | Verdict | Failing dimensions | Action |
|-------|---------|---------------------|--------|
| 1     | PASS    | —                   | Proceed to hand-off |

## Plan validation

- Date: 2026-09-09T15:00:00Z
- Verdict: PASS
- Wiring: PASS (no new production module created; `rollup_rebuild.py`/`db.py` are existing-file rewrites with no new entry point; `004_rollup_query_indexes.py` self-chains via its own `down_revision`, matching the `002_`/`003_` precedent; every other new file is a script or test leaf)
- Docs: PASS (no T1–T4 trigger fires — no new runnable surface, route, env var, or service/port; D-03 deliberately avoids the env-var path)
- Runner-setup: PASS (both the `integration`- and `performance`-typed TCs run through the already-installed `pytest`/`pytest-asyncio`/`migrated_db` stack; no new runner)
- Cross-section: PASS (verified programmatically against `tasks.json`: 13 tasks, 15 `file_plan` entries, DAG acyclic, every `file_plan` entry covered by ≥1 task, every task `files[]` id resolves, zero write conflicts between DAG-independent tasks; every test-strategy layer has a backing task; every research condition C-1..C-5 and every HIGH/MED/LOW risk except the accepted `R-09` maps to ≥1 task)
- Config drift: PASS (no new runtime dep/service/port — C1/C2/C3 do not fire)
- Decision-promotion: PASS (all 5 `DECISIONS.md` entries are `blast:feature`/`blast:service` + `rev:mechanical`; none requires `adr:` promotion)
- Rounds: 1
