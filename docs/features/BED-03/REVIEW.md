# Code Review — feature/BED-03

- Date: 2026-08-27T12:43:33Z
- Mode: story (GATE MODE — report-only, `/arh-implement` Validate ∥ Review gate, round 1)
- Files reviewed: 13 (4 modified, 9 new)
- Verdict: PASS

## Executive summary

BED-03 adds the rollup rebuild engine: `app/core/db.py` (session factory, D-02) and `app/services/rollup_rebuild.py` (`rebuild_program_rollups`/`rebuild_org_rollups`, D-01/D-03/D-05/D-06/D-08), wired into `app/main.py` and the services barrel export, documented in `services/api/README.md` and `docs/requirements/data.md`, and covered by 8 new test files (unit + perf). The diff matches `tasks.json`'s `file_plan` (F-01..F-15) exactly — no scope-creep. All load-bearing invariants hold: exactly one `SELECT` against `usage_events` per scope (verified by `before_cursor_execute` listener tests, D-05), every program-scoped DELETE is `program_id`-bounded (AC-4), the `_rebuild_transaction()` savepoint fallback is exercised on both the clean-session and already-open-transaction paths with full-rollback assertions against a separate verification session (D-01/D-08), and the `rollup_rebuild_completed` log carries only opaque ids (`scope`, `program_id`, `duration_ms`, `event_count` — no PII, verified end-to-end through the real `JSONFormatter`). `docs/requirements/data.md`'s contract section was updated in the same diff to the concrete signatures — no contract-drift.

🟢 strengths — exhaustive test coverage per invariant (transaction, query-plan, isolation, idempotency, observability, contract, perf), all via ORM bind parameters, D-01/D-03/D-05/D-06/D-08 all correctly implemented and cross-referenced.
⚠️ warnings — one stale doc comment (see below), otherwise clean.
🛑 blockers — none.

## Findings summary

| Severity | Count | Category distribution                        |
|----------|-------|-----------------------------------------------|
| CRITICAL |   0   | —                                              |
| HIGH     |   0   | —                                              |
| MEDIUM   |   0   | —                                              |
| LOW      |   1   | testability/docs (1)                           |

## Detailed findings

### LOW

#### F-1 — stale "open question" docstrings after D-07 resolved the mau_series bucket
- Category: testability (documentation accuracy)
- Path: `services/api/app/services/rollup_rebuild.py:388-389` (`_build_mau_series` docstring: "not an explicit decision — flagged for confirmation"); `services/api/tests/unit/test_rollup_rebuild_org.py:15-21` (module docstring: "Known open question (queued for PO clarification...)")
- Source: `docs/features/BED-03/DECISIONS.md` D-07; `docs/features/BED-03/QUESTIONS.md` (resolved 2026-08-27, "no code change required")
- Description: Both comments still present the `developer`-bucket choice as an open/unconfirmed question. D-07 settled it explicitly and QUESTIONS.md confirms no code change was needed, so the code is already correct — only the prose is out of date. A future reader (or another agent) could mistake this for a still-open item.
- Suggested fix: Update both docstrings to reference D-07 as the settled decision (matching the pattern already used elsewhere in the module, e.g. the D-03/D-04/D-08 citations). Not blocking — no functional or contract impact.

## What went well

- Every load-bearing invariant (D-01 atomicity, D-05 single-SELECT, AC-4 program isolation, D-04 idempotency comparison) has a dedicated test file that exercises both the happy path and the specific failure/edge shape (mid-rebuild exception, 10-program fan-out, stale-row deletion, savepoint fallback).
- `_rebuild_transaction()`'s two-branch design (D-08) is tested on both branches independently with rollback verified through a session that never touched the failed transaction — a genuinely rigorous atomicity proof.
- Security posture verified directly: AST-based check that neither public function constructs its own session/engine, grep-based check that no router references the rebuild functions, and a real end-to-end log-capture asserting no PII field survives the production `JSONFormatter`.
- `docs/requirements/data.md` and `services/api/README.md` were updated in the same diff as the code that changes their claims — no contract-drift.

## Recommendation

PASS. No action required before proceeding to validation join. The one LOW finding (stale docstrings referencing an already-resolved D-07 question) may be picked up opportunistically in a future touch of these two files; it does not block merge.
