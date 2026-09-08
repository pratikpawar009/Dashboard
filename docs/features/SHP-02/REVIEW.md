# Code Review — feature/SHP-02

- Date: 2026-09-08T00:00:00Z
- Mode: current (gate mode — invoked from `/arh-implement` Validate ∥ Review gate)
- Files reviewed: 18 (7 new source/migration/test, 4 modified source, 4 test/fixture, 1 new ADR, docs: README/RTM/api.md/story)
- Verdict: PASS WITH WARNINGS

## Executive summary

`GET /api/personal-usage/{user_id}` is implemented exactly to ADR-0009's sealed envelope: 4
order-locked 5-key cards (no `delta`), a range-scoped raw `daily_tokens` series, and a range-scoped
`commands` panel with the max-of-range (not share-of-total) bar formula. Independently recomputing
TC-01's arithmetic by hand (card totals, zero-padded daily series, command bar widths) against the
seeded fixture confirms every asserted value is correct — no drift between contract, code, and
tests. RBAC (`individual_usage_visibility`), the D-02 range-default wrapper, the D-01 3-SELECT
table split, and the D-05 ORM/migration index mirroring are all implemented as decided. Contract
docs (`api.md`, `README.md`, `RTM.md`, the story file) are updated in the same diff — no
contract-drift. The four out-of-plan file edits (F-12..F-15) are exactly the authorized,
narrowly-scoped fixes tasks.json describes. No security anti-patterns found in the new/changed
files.

🟢 Faithful ADR/DECISIONS implementation, verified-by-hand arithmetic, contract docs updated in-diff, clean SAST scan
⚠️ One traceability mismatch between `tasks.json` F-14 and the `FLAGS.md` id it cites; `impl_evidence` carries a recorded BLOCKED-with-override (already fully justified, not a fresh finding)
🛑 None

## Findings summary

| Severity | Count | Category distribution |
|----------|-------|------------------------|
| CRITICAL |   0   | — |
| HIGH     |   0   | — |
| MEDIUM   |   0   | — |
| LOW      |   1   | testability/traceability (1) |

## Detailed findings

### LOW

#### F-1 — testability: `tasks.json` F-14 cites the wrong `FLAGS.md` id
- Category: testability (documentation/traceability)
- Path: `docs/features/SHP-02/tasks.json:174-175` vs `docs/features/SHP-02/FLAGS.md` (AF-07)
- Source: internal cross-reference between this story's own artifacts
- Description: `tasks.json`'s F-14 entry (the `tests/fixtures/prd_8_4_schema.json` correction for
  the two new D-05 indexes) says "See FLAGS.md AF-07." The actual AF-07 in `state.json`/`FLAGS.md`
  is "design_check dimension recorded N/A — no a11y/console-scan tool wired," an unrelated flag.
  `EVIDENCE-ROUNDS.md` Round 1 independently confirms the fixture fix itself is correct and fully
  verified (`test_models.py` 46/46 green) — this is a citation drift, not a code defect.
- Suggested fix: correct F-14's `reason` string to point at the right flag id (or "authorized
  directly during evidence pass round 1, no AF-id" if none was ever assigned) in a follow-up doc
  edit — no source change needed.

## What went well

- ADR-0009's full envelope (5-key cards, order lock, no `delta`, to-date-vs-ranged split,
  max-of-range bar formula) is implemented verbatim — verified by re-deriving TC-01's own expected
  values from its seed data independently of the shipped test assertions.
- D-01's 3-bounded-`SELECT` table split (`user_sessions` for cards+chart, `usage_events` for
  commands only) is exactly what `app/services/personal_usage.py` does; the new composite indexes
  in the Alembic migration and the ORM `__table_args__` (D-05) match column-for-column.
- D-02's `_range_with_default` wrapper delegates 100% of validation/logging/error-body behavior to
  the existing shared `validate_range()` — zero edits to `app/dependencies/range.py`.
- D-03's `bar_style_for_share()` is purely additive to `app/utils/format.py`, matches
  `dot_style_for_program()`'s "producer computes CSS" precedent, and got its own direct unit
  coverage (F-15) with a correct round-half-to-even boundary table.
- `docs/requirements/api.md#personal-usage-api`, `README.md`'s API table, `docs/adr/README.md`, and
  `docs/stories/SHP-02.md` are all updated in the same diff — the sealed contract does not go stale
  for its four sibling consumers (ARC-01/DEV-01/PMD-01/PGD-05).
- Clean SAST-pattern scan (no eval/exec/shell=True/XSS-sink/weak-crypto patterns) across every new
  file.
- The four unplanned file edits (F-12..F-15) are each a narrowly-scoped, user-authorized fix
  (dynamic `HEAD_REVISION`, TC-01 arithmetic correction, stale fixture, `bar_style_for_share` unit
  test) — no unrelated drive-by changes riding along.

## Recommendation

PASS WITH WARNINGS. The single LOW finding is a documentation cross-reference nit inside this
story's own artifacts, not a source-code or contract issue — safe to carry forward as a PR-body
note rather than a fix-round blocker. The recorded `impl_evidence` BLOCKED verdict (6 pre-existing,
non-SHP-02 perf-test files, proven code-independent via git-stash A/B, human-overridden) is an
already-adjudicated evidence-pass matter, not a fresh review finding, and does not change this
verdict.
