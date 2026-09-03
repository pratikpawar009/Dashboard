# Code Review — feature/ING-01 (round 3)

- Date: 2026-09-03T00:00:00Z
- Mode: current (GATE MODE — report-only, `/arh-implement` Validate ∥ Review gate, round 3 of 3, content anchor `71196cb3614d`)
- Source snapshot: working tree (feature/ING-01 HEAD == `c918c37`; ING-01 is entirely uncommitted; local `main` ref is stale at `1d3f740` — AUTH-03/AUTH-04 are already on HEAD's history but not on local `main`, so `git diff main...HEAD` over-includes them. The actual ING-01 diff is the working-tree delta: `git diff HEAD --stat` (tracked) + untracked new files, verified against `git status`.)
- Files reviewed: full re-review. Changed since round 2 (5): `services/api/scripts/mint_ingest_token.py`, `docs/requirements/auth.md`, `services/api/tests/unit/test_mint_ingest_token.py`, `docs/test-cases/ING-01.json`, `docs/features/ING-01/DECISIONS.md`. Re-checked unchanged for interaction effects (5): `app/core/ingest_auth.py`, `tests/unit/test_ingest_token_auth.py`, `tests/unit/test_ingest_token_isolation.py`, `tests/perf/test_ingest_token_auth_perf.py`, `services/api/README.md`.
- Verdict: **PASS**

## Executive summary

Both round-2 findings are fixed and hold up under exhaustive, empirical re-testing. F-2 (CRITICAL): `_parse_program_ids` now guards on `if raw is None:` instead of `if not raw:`, so a genuinely omitted `--program-ids` (`raw is None`) is the only path to the allow-all `[]` default — every supplied value, including `""`, is routed through the trim/drop/usage-error logic. F-3 (HIGH, contract-drift): `docs/requirements/auth.md#ingest-token-auth`'s `mint_surface` now states the trim/drop/usage-error behavior explicitly and cites D-04/D-05a; it matches the shipped code field-for-field. DECISIONS.md gained D-05a, a sound, ADR-0006-compliant amendment that narrows only CLI input-validation surface, touching neither §3 (scope semantics) nor §4 (lifetime default). The fix stayed surgical — only `_parse_program_ids` and its docstrings changed in the script; the four `*_regression_f1` tests remain genuine (none exercise the `raw is None` branch, so none went tautological); a new `*_regression_f2` test (`ING-01-TC-25`) closes the exact gap round 2 found.

🟢 Strengths: fail-open path empirically closed across every input shape tested; contract doc now matches code; decision log records the actual history (including its own prior mistake) rather than hiding it; regression coverage added without disturbing existing tests; full unit-test/mypy/ruff suite green, no dev-DB writes.

⚠️ Warnings: none blocking. One record-keeping observation below (not a finding) on how D-05 was amended in place.

🛑 Blockers: none.

## Findings summary

| Severity | Count | Category distribution |
|----------|-------|------------------------|
| CRITICAL | 0 | — |
| HIGH | 0 | — |
| MEDIUM | 0 | — |
| LOW | 0 | — |

No new findings this round. Round 2's F-2 (CRITICAL, safety-security) and F-3 (HIGH, contract-drift) are both resolved — see verification below, not restated as open.

## Fail-open path — verdict: CLOSED

Exhaustively traced every input the reviewer brief listed, plus the two argparse edge forms, both by reading `_parse_program_ids`/`_parse_args` (`services/api/scripts/mint_ingest_token.py:45-100`) and by executing them in-process against the actual functions:

| Input | Result | Correct? |
|---|---|---|
| `None` (flag omitted entirely) | `[]` (allow-all) | Yes — the only sanctioned path to allow-all |
| `""` (`--program-ids ""`) | `ValueError` (usage error) | Yes — this is the exact F-2 regression case |
| `"--program-ids="` (argparse `=`-form, empty value) | `raw=''` → `ValueError` | Yes — argparse treats this as a supplied empty string, same as above, not `None` |
| `" "`, `"\t"`, `"\n"` | `ValueError` | Yes |
| `","`, `",,"`, `" , "` | `ValueError` | Yes |
| `",a"` | `["a"]` | Yes — leading empty element dropped, one usable id survives |
| `"a,"` | `["a"]` | Yes — trailing empty element dropped |
| `"*"`, `" * "` | `["*"]` | Yes — wildcard survives trimming |
| bare `--program-ids` with no following value | argparse `SystemExit(2)` before `_parse_args` returns | Yes — non-zero exit, no DB write, no stdout, occurs before `_run`'s try block even starts |

No supplied value reaches `[]`. `raw is None` is the sole omission signal, and it is set only when argparse never sees the flag at all. Ordering is confirmed airtight: `_run()` calls `_parse_program_ids` before `_mint()` (`services/api/scripts/mint_ingest_token.py:123-131`), inside the same `try` — any `ValueError` is caught, printed to stderr, and returns exit code 1 before any DB session is opened. Empirically verified: direct in-process calls against every row above, plus `test_mint_ingest_token.py` (11/11 passing, including `test_mint_supplied_empty_program_ids_is_usage_error_regression_f2`) and `test_ingest_token_auth.py` + `test_ingest_token_isolation.py` (17/17 passing, re-run for interaction effects) — all against the disposable `dashboard_test` database (`tests/conftest.py:75-93`), never the dev database. No source file was edited to perform this trace.

## D-05a — judgement

**Sound decision.** It correctly narrows only the mint CLI's input-validation boundary (`raw is None` vs. any supplied value) and leaves ADR-0006 §2 (mint surface), §3 (scope semantics: empty-array-allow-all, wildcard), and §4 (lifetime default) completely untouched — confirmed by re-reading `docs/adr/0006-ingest-token-format-and-scope-semantics.md` §3/§4 against D-05a's text. **Code matches it**: `if raw is None: return []` (`mint_ingest_token.py:91-92`) is the literal, minimal implementation of the decision.

**D-05 retained with a forward pointer — acceptable, with one nuance.** D-05a's own Context section is honest about the history: it states plainly that "D-05 as first written put `raw is None` **or** `""` in the omission set" and that the implementation faithfully encoded that bug — so the audit trail of what went wrong and why is preserved and is not hidden. However, D-05's own *Decision* paragraph has been lightly edited in place (not left byte-for-byte as originally written): it now reads "...reachable **only** by omitting `--program-ids` entirely (`raw is None` — see the D-05a amendment below, which removes `""` from this set)" — i.e., D-05's Decision text itself already states the corrected rule, with an inline pointer, rather than preserving its original (incorrect) wording verbatim and letting D-05a be the sole place the correction lives. This is not misleading — a reader of D-05 alone gets an accurate description of current behavior, and D-05a's Context section is where the actual mistake and its consequence are recorded — but it is a stricter-than-usual amendment style (edit-in-place-with-forward-note, rather than freeze-and-supersede). Worth naming so future amendments in this log follow one convention deliberately rather than by accident; not a defect, not blocking.

## Contract accuracy — `auth.md` vs. code

`docs/requirements/auth.md#ingest-token-auth`'s `mint_surface` field now states, verbatim: trim behavior, empty-element dropping, "`allowed_program_ids=[]` (allow-all) is reachable ONLY by omitting `--program-ids` entirely (DECISIONS.md D-04, D-05a)", and explicitly lists `""`, `" "`, `","` as usage-error examples. This is an exact match to the shipped `_parse_program_ids` behavior and to D-05a. Round 2's F-3 gap (contract silent on D-05's trim semantics) is closed. Three downstream stories (ING-02, ING-03, ING-07) can now bind to this contract without cross-referencing `DECISIONS.md` to learn the real input-validation behavior.

## Test-quality checks

- **TC-25 (`ING-01-TC-25`)**: asserts exactly what it claims — non-zero exit, empty stdout, zero DB rows for `--program-ids ""` — matching `requirement_id: ING-01-FR-2` and `tags: [..., "regression-f2"]`. Its `test_data` (`label`, `user_email`, `program_ids: ""`) is plain literal values, not `<PLACEHOLDER>` form — but this matches the established pattern for every other mint-CLI test case in the same manifest (TC-01, TC-02, TC-04, TC-05, TC-23 all use plain literals for label/email/program_ids). `<PLACEHOLDER>` form in this manifest is reserved for pre-generated *secrets* (`<RAW_TOKEN>` etc., used by the `get_ingest_token` auth-check test cases, TC-06 onward, which need a token minted ahead of test execution). TC-25 correctly follows its sibling group's convention; no inconsistency.
- **The four `*_regression_f1` tests remain meaningful, not tautological.** All four supply non-`None` `raw` values (`"a, b"`, `"a,,b"`, `"*"`, `" "`/`","`) and assert trim/drop/wildcard/usage-error outcomes — none of them exercise the `raw is None` branch the D-05a fix touched, so the `if not raw:` → `if raw is None:` change does not affect their behavior or their ability to fail against a regression. Confirmed by reading each assertion against the current `_parse_program_ids` body.
- **Coverage audit**: `docs/test-cases/ING-01.json` — 25 cases, `coverage_audit.uncovered: []`, `ING-01-FR-2.covered_by` includes `ING-01-TC-25`. Matches orchestrator's figures.

## Scope discipline

- **scope-creep**: none. All 5 round-3-changed files trace to `tasks.json`'s `file_plan`: `mint_ingest_token.py` → F-01 (T-02), `test_mint_ingest_token.py` → F-03 (T-03), `auth.md` → F-08 (T-07). `DECISIONS.md` and `docs/test-cases/ING-01.json` are standard per-feature artefacts (decision log, test-case manifest) outside the code `file_plan` by convention, consistent with round 1/2's same pattern. The script diff itself stayed inside `_parse_program_ids` and its docstrings — no changes to `_parse_args`, `_mint`, `_run`, or `main`.
- **adr-violation**: none. D-05a does not touch ADR-0006 §2/§3/§4 (verified above).
- **contract-drift**: none remaining — F-3 (round 2) is closed.

## Independent verification

- `uv run pytest tests/unit/test_mint_ingest_token.py -q` → 11 passed.
- `uv run pytest tests/unit/test_ingest_token_auth.py tests/unit/test_ingest_token_isolation.py -q` → 17 passed (unchanged files, re-run for interaction effects; only pre-existing, unrelated `on_event` deprecation warnings from `app/main.py`).
- `uv run ruff check scripts/mint_ingest_token.py tests/unit/test_mint_ingest_token.py` → all checks passed.
- `uv run mypy scripts/mint_ingest_token.py` → no issues.
- `_parse_program_ids`/`_parse_args` exercised directly, in-process, against every input in the reviewer brief plus the `--program-ids=` and bare-flag argparse forms — read-only, no DB touched, no dev database written to. All 5 tracked files' diffs and all 5 untracked new/modified ING-01 files read in full for this round.
- No source file edited. No `state.json` or `docs/state/features.json` written (GATE MODE — orchestrator applies state after the join).

## Already-settled items not re-raised

Empty-array-allow-all / null-`expires_at` (ADR-0006 §3/§4), 403-not-404 for out-of-scope program (ADR-0006 § Flagged gaps), 64-hex/32-byte token format (ADR-0006 §1), per-reason 401 `detail` (AF-02, triaged reject) — all unchanged and not re-raised.

## What went well

- `if raw is None:` is the minimal, correct fix — exactly the one-line change round 2 prescribed, with no scope creep into adjacent logic.
- D-05a's Context section documents its own predecessor's mistake honestly rather than quietly erasing it — good audit-trail discipline even where the in-place edit to D-05's Decision text (see nuance above) could have been handled more conservatively.
- `auth.md`'s contract is now precise enough that ING-02/03/07 don't need to cross-reference `DECISIONS.md` to learn real mint-CLI behavior.
- Regression coverage added surgically: one new test, no disturbance to the four existing `*_regression_f1` tests.

## Recommendation

**PASS.** No CRITICAL, HIGH, MEDIUM, or LOW findings this round. The fail-open path first identified in round 1 (untrimmed whitespace) and narrowed further in round 2 (`""` bypassing the omission guard) is now closed for every input shape tested, including the two argparse edge forms (`--program-ids=`, bare flag with no value) added to this round's scrutiny. Proceed to `/arh-security-review`.
