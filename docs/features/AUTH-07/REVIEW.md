# Code Review — feature/AUTH-07 (Round 3 — narrow re-verification)

- Date: 2026-09-11T09:15:00Z
- Mode: story (GATE MODE — report-only, invoked by /arh-implement Validate ∥ Review gate)
- Prior rounds: Round 1 BLOCKED on F-1 (AF-04/AC-7 cache bypass). Round 2 PASS — F-1 resolved at root
  cause, F-2/F-3/F-4/F-5/F-6 carried forward. Both agents PASSed Round 2; gate was GREEN.
- Trigger for this round: two edits landed AFTER the Round-2 passing gate, at the user's explicit
  direction ("fix them then commit") to close AF-01 and AF-02 before commit. Per the sequence rule,
  any post-gate edit invalidates both verdicts — this round re-verifies the total diff with those two
  edits included.
- **Post-gate delta, confirmed by direct diff (not assumed):** exactly 2 files, +14/-0 lines —
  `services/api/tests/conftest.py` (+13, `_HERMETIC_SETTINGS_DEFAULTS`) and
  `.claude/skills/alembic-patterns/SKILL.md` (+1, anti-pattern bullet). Confirmed via
  `find services/api/app -newer services/api/tests/conftest.py` → empty: **no file under
  `services/api/app/` is newer than conftest.py's edit**, i.e. production code is genuinely
  byte-identical to Round 2, not merely claimed to be.
- Verdict: **PASS**

## 1. Is the `conftest.py` pin correct and safe?

**Yes — verified empirically, not read on its face.**

`_HERMETIC_SETTINGS_DEFAULTS` (`services/api/tests/conftest.py:757-799`) gains two keys:
`"frontend_login_url": None` and `"persona_precedence_order": None`. Both fields already default to
`None` at the `Settings` class level (`app/core/config.py:62,98`), so the pin only matters for
pydantic-settings' precedence order (constructor kwarg > env var > `.env` file > field default) — it
forecloses a real `FRONTEND_LOGIN_URL`/`PERSONA_PRECEDENCE_ORDER` in a developer's shell or a stray
`services/api/.env` from leaking into a `build_app()` test, exactly the class of bug the surrounding
comment's 2026-09-08 `oidc_redirect_uri` incident already documents.

Ran two independent checks rather than trusting the docstring:

- **Zero-mutation counterfactual** (`uv run python -c ...`, poisoned env `FRONTEND_LOGIN_URL`/
  `PERSONA_PRECEDENCE_ORDER` set): constructing `Settings(**_HERMETIC_SETTINGS_DEFAULTS)` yields
  `frontend_login_url=None`, `persona_precedence_order=None` — hermetic. Constructing `Settings(**{k:v
  for k,v in _HERMETIC_SETTINGS_DEFAULTS.items() if k not in these two keys})` (the pre-fix shape)
  under the same poisoned env yields `frontend_login_url='https://leaked-from-env.example.com'`,
  `persona_precedence_order=['cio']` — proving the pre-fix gap was real, not hypothetical, and that
  the fix closes it.
- **Full affected-file test run** with the SAME poisoned env vars still exported:
  `uv run pytest tests/unit/test_auth_logout.py tests/unit/test_auth_config.py
  tests/unit/test_persona_resolver.py -q` → **103 passed**, 0 failed. The "unset → 501" completeness-
  gate branch and the all-tiers-unset `_DEFAULT_PERSONA_PRECEDENCE` branch stayed deterministic even
  with a poisoned environment present — the pin does what it claims.
- Per-call overrides still win: `test_auth_logout.py`'s `_configured_overrides()` passes
  `frontend_login_url` explicitly on every `build_app()` call for the configured-path tests, and those
  passed too (constructor kwargs are the highest-precedence source in `{**_HERMETIC_SETTINGS_DEFAULTS,
  **overrides}`, `conftest.py:823`) — T-08's configured cases are unaffected.
- `ruff check tests/conftest.py` and `mypy tests/conftest.py` — both clean.
- Masks nothing legitimately relied on: no test in the affected files reads
  `frontend_login_url`/`persona_precedence_order` from an *unset* `build_app()` call expecting a
  non-`None` value — every configured case supplies its own value via `**overrides`.

## 2. Does it close Round-1 F-4 / AF-01?

**Yes — resolved, confirmed by the test above.** F-4 (`REVIEW.md` Round 2) and `FLAGS.md`'s AF-01 both
described the identical gap: the two new fields were absent from `_HERMETIC_SETTINGS_DEFAULTS`, so the
"unset → 501" and all-tiers-unset branches were only accidentally deterministic. The 13-line addition
is the exact fix that gap called for, applied surgically (only the dict, nothing else in the 700+ line
file touched), and independently verified above rather than taken from the comment's own claim.

## 3. Any new regression in the frozen invariants?

**None.** No production code changed (confirmed above by mtime + zero hits in `git diff` outside the
two named files). Frozen invariants from Round 2 (persona_resolver cache sharing, `resolve()` signature,
`rbac-checks` consumers, AC-21/22/23/26, DATA-DESIGN.md §8) are untouched by this delta and were not
re-derived, per this round's own scope — Round 2 already verified them against the actual fix, and
nothing in this round's two files can affect them (one is a test-fixture dict, the other is a markdown
skill file).

**One new observation, not a regression:** `tests/unit/test_auth_logout.py:8-14`'s own module docstring
still reads *"AF-01 (T-01 flag): `tests/conftest.py`'s `_HERMETIC_SETTINGS_DEFAULTS` does NOT pin
`frontend_login_url`..."* — now factually stale, since the pin exists as of this delta. This is
cosmetic, not functional: the file's tests never relied on the absence of the pin (every call passes
`frontend_login_url` explicitly via `_configured_overrides()`), so nothing breaks or is masked. Filed
as F-7 below (LOW), same class as Round 2's F-6 (stale FLAGS.md text), which that round correctly
treated as non-blocking.

## Findings summary

| Severity | Count | Category distribution |
|----------|-------|------------------------|
| CRITICAL | 0 | — |
| HIGH | 0 | — |
| MEDIUM | 2 | contract-drift (1, F-2 — carried, unchanged), data-integrity/scope (1, F-3 — carried, unchanged) |
| LOW | 2 | testability (1, F-5 — carried, unchanged), process-doc (1, F-7 — new) |

Two prior findings close this round: **F-4/AF-01 → RESOLVED** (see §2 above). **F-6 → RESOLVED** —
`FLAGS.md`'s AF-04 entry has been rewritten with its full round-2 resolution narrative, and all seven
flags (AF-01…AF-07) are now triaged with 0 open (verified by reading `FLAGS.md` directly: AF-01/AF-02
"FIXED", AF-03 "resolved-no-action", AF-04 "resolved (gate round 2)" with the resolution text present,
AF-05 "resolved", AF-06/AF-07 "confirmed N/A").

## Carry-forward (unchanged from Round 2, not escalated — no new evidence)

### F-2 — contract-drift: `persona-resolver`'s `cache` field (MEDIUM)
`docs/requirements/auth.md:36` still untouched; underlying gap closed by the Round-2 fix, remaining
item is a documentation-clarity nicety (naming `resolve_precedence` as a second cache consumer).

### F-3 — `docs/activity/activity.jsonl` mutates a pre-existing historical row (MEDIUM)
Same row as prior rounds; recurring harness-telemetry pattern, unrelated to this story's code.

### F-5 — `migrated_db` fixture is rapid-cycle-flaky under partial test selection (LOW)
`services/api/tests/conftest.py:254-266`. Not triggered by AUTH-07's code; not re-exercised this
round (this round's own test runs used full-file selection, which Round 2 already confirmed doesn't
trigger it).

## New this round

### F-7 — stale AF-01 narration in `test_auth_logout.py` module docstring (LOW)
- Category: testability / process-doc
- Path: `services/api/tests/unit/test_auth_logout.py:8-14`
- Source: this round's direct verification (mechanical check of the fix's own narration, not the
  narration's face value)
- Description: the docstring asserts `conftest.py` does NOT pin `frontend_login_url`, which was true
  when T-08 wrote it but is now false — the AF-01 fix in this round's delta pins it. No functional
  effect (every `build_app()` call in the file already passes the field explicitly), but a future
  reader would draw a false conclusion about why the file's overrides are necessary.
- Suggested fix: one-line docstring update in a follow-up touch of this file, noting the pin now
  exists and the explicit overrides remain for clarity/defense-in-depth rather than necessity.

## Escalation state

`gate_rounds` was 2 entering this round; this is round 3 of the hard cap of 3, closed **PASS** — no
escalation, no `REVIEW-ESCALATION.md` needed.

## Recommendation

**PASS.** The entire post-gate delta is a 13-line test-fixture default addition and a 1-line
documentation bullet — verified correct, safe, and narrowly scoped by direct experiment (not
assumption): a zero-mutation counterfactual proved the pre-fix gap was real and the fix closes it,
and the affected test files (103 tests) pass under a deliberately poisoned environment. No production
code changed (confirmed by mtime check). F-4/AF-01 and F-6 are resolved and close out this round; F-2/
F-3/F-5 carry forward unescalated per the round's instruction; F-7 is a new, non-blocking cosmetic
observation. No CRITICAL/HIGH, 2 MEDIUM, 2 LOW — clears the PASS threshold.
