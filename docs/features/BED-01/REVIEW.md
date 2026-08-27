# Code Review — feature/BED-01 (round 2, GATE MODE — report-only)

- Date: 2026-08-27T09:30:00Z
- Mode: story (GATE MODE — report-only, `/arh-implement` Validate ∥ Review gate, round 2 of 3)
- Files reviewed: 1 changed since round 1 (`services/api/tests/test_models.py`), plus re-confirmation of the 13 other in-scope files reviewed in round 1 (unchanged)
- Verdict: PASS

## Executive summary

Since round 1 (PASS WITH WARNINGS, one HIGH — F-1), exactly one file changed: `services/api/tests/test_models.py`. The change adds fixture-driven table-level constraint verification (`_parse_fixture_constraints`, `_actual_table_constraints`, `_compare_constraints`, `TestFixtureDrivenTableConstraints` parametrized across all 18 tables, plus a deliberate-mismatch meta-test). F-1 is genuinely resolved, not papered over — verified below by cross-checking the parser's regex against the actual fixture strings and the actual SQLAlchemy introspection output for all 18 tables, not by re-reading the test's own assertions. No scope creep: mtimes confirm every other in-scope file (models, migration, fixtures, conftest, docs, ADR, data.md) predates this file's last edit, and `git status` shows no other file touched this round. F-2 and F-3 remain open as accepted carry-forward, unchanged, not re-raised as blocking.

🟢 strengths: constraint gate now has real teeth across all 18 tables, single-column `unique=True` case independently verified to materialize as an inspectable `UniqueConstraint` (not silently missed), non-vacuous meta-test, legitimate `cast` usage.
⚠️ warnings: F-2, F-3 carried forward (unchanged, accepted, non-blocking).
🛑 blockers: none.

## Findings summary

| Severity | Count | Category distribution |
|----------|-------|------------------------|
| CRITICAL |   0   | — |
| HIGH     |   0   | — |
| MEDIUM   |   0   | — |
| LOW      |   2   | testability (2) — carry-forward, unchanged from round 1 |

## Verification detail (this round's specific checks)

**1. F-1 resolution — is the parser trivially green, or does it actually check?**
Extracted every table's `constraints` fixture entry directly from `tests/fixtures/prd_8_4_schema.json` and independently introspected `table.constraints`/`table.indexes` for all 18 live models (via direct Python import, not by trusting the test's own output). Result: fixture and actual match exactly, entry-for-entry, for every table, including:
- Multi-column `UniqueConstraint`s (`token_series`, `mau_series`, `session_series`, `program_token_series`, `program_artifacts`, `program_guardrails`, `org_constitution`, `usage_events`) — correctly parsed and correctly matched.
- Single-column `unique(...)` entries backed only by `mapped_column(unique=True)` (`org_summary_rollup.org_id`, `program_summary.program_id`, `ingest_tokens.token_hash`, `user_sessions.session_identifier`) — confirmed these *do* materialize as a real `UniqueConstraint` on `table.constraints` (not just a column flag SQLAlchemy never surfaces structurally), so `_actual_table_constraints` genuinely captures them rather than the check being vacuously satisfied by an empty actual-set.
- Prose-only entries (`org_summary_rollup`'s "— singleton, org_id default 'org-1'" suffix; `ingest_tokens`' "no column stores the raw token..." note) — the `^(unique|index)\(...\)` regex uses `match()` (prefix-anchored, not `fullmatch`), so trailing prose after the parenthesized column list does not break parsing, and the fully-prose `ingest_tokens` entry (which doesn't start with `unique(`/`index(`) is correctly skipped rather than mis-parsed. Tables with genuinely empty `constraints: []` (`system_metadata`, `persona_config`, `user_roles`) correctly have an empty actual set too — confirmed no stray Index/UniqueConstraint exists on those models.

No entry in any of the 18 tables was silently dropped in a way that would make the assertion trivially pass. **F-1 is closed** — C-1's "constraints" clause now has real coverage across all 18 tables, at the fast model layer, not just the 2 tables previously covered at the live-DB layer.

**2. Meta-test strength.** `TestConstraintComparisonDetectsMismatch` clones `token_series`'s real table via `to_metadata()` into a throwaway `MetaData` (never mutates `Base.metadata`, which other tests in the session depend on), discards its `UniqueConstraint`, and asserts `_compare_constraints` reports it as `missing`. This exercises the actual comparison function end-to-end (not a mocked stand-in) and would fail if the diffing logic were vacuous. Confirmed sound.

**3. `typing.cast` legitimacy.** Isolated the cast in a scratch file and ran `mypy` with and without it: removing `cast(sa.Table, ...)` before the `.to_metadata()` call reproduces a real mypy error (`"FromClause" has no attribute "to_metadata"`), because `DeclarativeBase.__table__` is typed as `FromClause` in SQLAlchemy's stubs, not `Table`. At runtime the object is always a genuine `Table` for a mapped class. This is a legitimate narrowing of an ORM stub-typing gap, not suppression of a real logic error — no `.claude/rules` violation. `uv run mypy tests/test_models.py` passes clean with the cast in place.

**4. Scope check.** `stat` on every in-scope file shows `test_models.py` (09:17:24) is the only file with an mtime after round 1's `REVIEW.md` (09:12:13); models, migration, fixture, conftest, `data.md`, ADR-0003, and `docs/stories/BED-01.md` all predate it. No model, migration, fixture, conftest, or doc file was touched. Confirmed no scope creep.

**5. Round-1 conclusions re-confirmed (unchanged files, not re-audited line-by-line).** Contract fidelity (models ↔ `data.md` ↔ migration), `ingest_tokens` no-raw-token security property, `ruff`/`mypy` clean, ADR-0003/data.md contract currency, and the AF-04 dependency justification all stand as reported in round 1 — nothing in this round's single-file diff touches any of that surface.

## What went well

- F-1's fix is a genuine, non-vacuous closure of the C-1 acceptance gate, verified independently rather than taken on the diff's own assertions.
- Meta-test correctly exercises the real comparison function against a cloned (not mocked) table.
- `cast` usage is a legitimate, verified type-narrowing, not a suppression.
- Zero scope creep — mtime evidence confirms the fix touched exactly one file.

## Carry-forward (accepted in round 1, not re-raised, not fixed this round)

- **F-2** — `test_models.py` `TestFixtureDrivenModelShape` is one-directional (fixture → model only); no assertion catches an extra column added to a model that's absent from the fixture. LOW, testability, `docs/features/BED-01/PLAN.md` § C-1.
- **F-3** — `test_migrations.py::TestBuildOrder` (`:330-349`) trusts self-reported `completed_at` timestamps from `tasks.json` as a proxy for git history, per `docs/test-cases/BED-01.json` BED-01-TC-16. LOW, testability. Documented as an acceptable adaptation until real git history exists.

## Recommendation

PASS. F-1 is genuinely resolved with independently-verified non-vacuous coverage. No CRITICAL/HIGH/MEDIUM findings remain. F-2/F-3 stay as accepted, non-blocking carry-forward.
