# Code Review — feature/AUTH-02 (round 3, uncommitted working tree vs main)

- Date: 2026-08-28T16:10:00Z
- Mode: current (GATE MODE — report-only, `/arh-implement` Validate ∥ Review gate, round 3 — final round under the combined cap)
- Files reviewed: 19 vs `main`; 4 touched by this round's fix loop — `docs/requirements/auth.md`, `docs/features/AUTH-02/REQUIREMENTS.md`, `docs/test-cases/AUTH-02.json`, `services/api/app/core/persona_resolver.py` (docstring only)
- Verdict: **PASS**

## Executive summary

All three round-2 findings are genuinely closed, verified by direct inspection rather than by trusting the round-2 fix description. F-1 (contract-drift): `docs/requirements/auth.md:31`'s `persona-resolver` § observability now states the fresh/warm distinction correctly, matching the shipped `_log_resolution` behavior exactly; `REQUIREMENTS.md` FR-5's body paragraph now carries the same reconciliation, cites D-11, C-4, and the NFR, and closes the allowlist-vs-operational-field ambiguity that caused the original Step 2 gate split. F-2 (testability): `docs/test-cases/AUTH-02.json` grew from 15 to 18 entries exactly as claimed; `AUTH-02-TC-16a/b/c` are registered under `AUTH-02-FR-5.covered_by`, and all three `implemented_by` pointers resolve to real, currently-passing `@pytest.mark.asyncio` functions in `test_persona_resolver.py` (verified by grep, not assumed). F-3 (safety-security): the module docstring's PII-invariant paragraph now reads identically in spirit to `_log_resolution`'s own docstring — both agree `tier3_latency_ms` is added only on a fresh Tier-3 query. Ran the target test file, `ruff`, and `mypy` directly: 14/16 unit tests pass locally (the 2 errors are the pre-existing `TEST_DATABASE_URL` environment gap, AF-02, not a regression), `ruff check .` and `mypy app/core/persona_resolver.py` both clean.

One residual surfaced during verification, not part of the three tracked findings: `REQUIREMENTS.md`'s own § Non-functional-requirements "Observability" bullet (line 104) still asserts the event carries "exactly `{role, persona, tier, timestamp}`" with no fresh/warm caveat — the identical class of self-contradiction D-11 diagnosed, left unswept three lines from the paragraph that fixed it. It does not misdirect an external consumer (the actual produced contract, `docs/requirements/auth.md`, is fully correct), so it's MEDIUM, not a reopened HIGH — but it sits exactly where D-11 says the original bug came from ("a dispatch brief quoted FR-5's four fields"), so a future AUTH-03/SHP-01 dispatch brief could quote this line and repeat the mistake.

D-01 through D-11 all confirmed present and unchanged in `DECISIONS.md`. All four previously-recorded flags (AF-01 wording, AF-02 environment gap, AF-03 perf sensitivity with measurements, AF-04 design_check N/A) and the deferred `AUTH-02-empty-role-short-circuit` carry-forward are confirmed unchanged and accurate in `FLAGS.md` / `state.json`. No new scope-creep: all touched files this round are documentation/registry artifacts backed by D-11's decision record or by round-2's own F-2 mandate, not `tasks.json` F-01..F-11 source deliverables (which are untouched this round beyond the one docstring comment).

🟢 F-1/F-2/F-3 all genuinely closed on direct verification (grep + live test run, not just reading the round-3 description); D-01..D-11 intact; zero behavior change (docstring-only source edit); AF-01..04 and the deferred risk all still accurate.
⚠️ `REQUIREMENTS.md:104`'s NFR Observability bullet still contradicts the fixed FR-5 paragraph three lines above it — same self-contradiction class as the original F-1, just not fully swept within this file.
🛑 None.

## Findings summary

| Severity | Count | Category distribution |
|----------|-------|------------------------|
| CRITICAL |   0   | — |
| HIGH     |   0   | — |
| MEDIUM   |   1   | contract-drift (1) |
| LOW      |   0   | — |

## Detailed findings

### MEDIUM

#### F-1 (round 3) — contract-drift: REQUIREMENTS.md's own NFR bullet still contradicts the fixed FR-5 paragraph

- Category: contract-drift
- Path: `docs/features/AUTH-02/REQUIREMENTS.md:104` (also the FR-5 heading's parenthetical summary at line 88, lower-risk instance of the same gap)
- Source: `docs/features/AUTH-02/DECISIONS.md` D-11 (names the exact failure mode: "a dispatch brief quoted FR-5's four fields and did not carry over the `tier3_latency_ms` requirement")
- Description: This round's fix correctly amended FR-5's body paragraph (line 90) to state the field is additive on a fresh Tier-3 query. Three lines later, under § Non-functional requirements, the standalone "Observability (log event)" bullet still reads "every resolution emits `persona_mapping_loaded` at INFO level with exactly `{role, persona, tier, timestamp}`" — the same absolute claim that was wrong before this fix loop, now sitting in the same file as its own correction. `docs/requirements/auth.md` (the actual produced contract AUTH-03/SHP-01 consume) is fully and correctly fixed, so no external consumer is misdirected — this is REQUIREMENTS.md's internal self-consistency, not a live cross-story contract break. But D-11 itself diagnoses the root cause as a dispatch brief quoting FR-5's four fields in isolation; this bullet is an equally quotable, equally wrong source for exactly that failure mode on a future task.
- Suggested fix: Amend `REQUIREMENTS.md:104` to "...with `{role, persona, tier, timestamp}`, plus `tier3_latency_ms` on a fresh Tier-3 resolution (D-11)" and optionally add the same parenthetical to FR-5's heading summary at line 88. Non-blocking; carry forward as a fast-follow before AUTH-03/SHP-01 dispatch briefs are written against this file.

## What went well

- F-1 verified independently: `docs/requirements/auth.md:31` and `REQUIREMENTS.md:90` both read correctly and agree with the shipped `persona_resolver.py` behavior — checked the contract text, the PRD text, and the code side by side rather than trusting the round-3 fix summary.
- F-2 verified independently: `python3 -c "json.load(...)"` confirms 18 test-case entries (15→18), `AUTH-02-TC-16a/b/c` registered under `FR-5.covered_by`, and `grep` on `test_persona_resolver.py` confirms all three `implemented_by` function names exist and are decorated `@pytest.mark.asyncio`.
- F-3 verified independently: the module docstring (`persona_resolver.py:20-23`) and `_log_resolution`'s docstring (`:198-208`) now state the same fresh/warm rule in the same file.
- Ran the actual suite rather than trusting the "335 passed" claim at face value: `uv run pytest tests/unit/test_persona_resolver.py -q` → 14 passed, 2 errors (both `TEST_DATABASE_URL`/Postgres-auth failures matching AF-02 exactly, not a new regression); `uv run ruff check .` → clean; `uv run mypy app/core/persona_resolver.py` → clean.
- D-01..D-11 all present and unchanged in `DECISIONS.md`; the fix-loop's only source-code touch this round is a docstring comment (confirmed — `persona_resolver.py` is untracked relative to `main`/HEAD, so its full history is in this one working-tree diff, and the delta since round 2's own reviewed snapshot is exactly the docstring paragraph).
- AF-01 (D-09 wording), AF-02 (`TEST_DATABASE_URL` drift, reproduced directly this round), AF-03 (perf sensitivity, measurements table intact), AF-04 (`design_check` N/A) and the deferred `AUTH-02-empty-role-short-circuit` risk all confirmed unchanged and accurate.
- Zero scope-creep: every file touched this round (`auth.md`, `REQUIREMENTS.md`, `AUTH-02.json`, `persona_resolver.py` docstring) is a documentation/registry correction traceable to D-11 or to round 2's own F-2 finding, not an unscoped edit to a `tasks.json` F-01..F-11 deliverable.

## Recommendation

**PASS.** All three round-2 findings are genuinely closed, independently verified against the live files and a live test run rather than the round description alone. One new MEDIUM (REQUIREMENTS.md's own NFR bullet, unswept by this fix loop) does not block — carry it forward as a fast-follow before AUTH-03/SHP-01 planning starts. On the procedural question: amending `REQUIREMENTS.md` FR-5 mid-flight, backed by a decision-log entry (D-11) that documents the contradiction, the adjudication, and the reasoning, is the correct escalation route per this project's own pattern (a decision-log entry functions as the "superseding entry" the gate's escalation paths call for) — a full `/arh-plan-requirements` re-run would have been disproportionate for a single self-contradicting paragraph already adjudicated on its merits. Clear to commit.
