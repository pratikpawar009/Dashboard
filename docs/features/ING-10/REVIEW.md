# Code Review — feature/ING-10

- Date: 2026-09-08T18:05:00Z
- Mode: story (GATE MODE — report-only, invoked from `/arh-implement` Validate ∥ Review gate) — Round 3 (FINAL, combined cap)
- Source snapshot anchor: `1b5907c8fdc14c84` (round 2 was `90cc54b541256722`, round 1 was `49700d5d1c1a37cb`)
- Files reviewed: 6 (round-3 delta: `docs/requirements/api.md`, `docs/features/ING-10/REQUIREMENTS.md`, `docs/features/ING-10/PLAN.md`, `services/api/app/api/manifest.py`, `services/api/tests/unit/test_manifest_roster_removal.py`, `services/api/tests/unit/test_manifest_payload_cap.py`) + 10 cross-referenced to verify carried findings and this round's role-mapping consistency ask (`services/api/app/core/role_map.py`, `services/api/config/persona_role_map.yaml`, `services/api/app/services/manifest_ingest.py`, `services/api/app/core/ingest_auth.py`, `services/api/app/main.py`, `services/api/tests/conftest.py`, `docs/features/ING-10/tasks.json`, `docs/features/ING-10/DECISIONS.md`, `docs/requirements/data.md`, `docs/activity/activity.jsonl`)
- Verdict: **PASS**

## Executive summary

Round 3 closes three findings from round 2 (one code-review's, `F-2` MEDIUM on `manifest.py`'s docstring; one code-review's, `F-4` LOW on the unused `repopulate()` helper; one validation's carry-forward on `api.md`'s stale `role_mapping` enumeration) and re-verifies every carried, deliberately-unfixed item is still exactly where round 2 left it. All three closures are independently confirmed against the current code, not just re-read from the prompt's claim: `manifest.py`'s docstring now describes the AF-09 fix accurately with no new inaccuracy in either direction; both `repopulate()` call sites import and call the real helper, which is byte-identical in behavior to the inline `.execution_options(populate_existing=True)` it replaces, so AF-14's re-read guard is not weakened; and `api.md`/`REQUIREMENTS.md:73`/`PLAN.md:118` all now enumerate the 6-slug map with `admin` called out as deliberately removed, consistent with `role_map.py`'s actual `_ROLE_SLUG_TO_PERSONA` dict, `data.md`'s `role_semantics`, and `DECISIONS.md` D-10/D-11.

One new MEDIUM surfaced from the explicit cross-check this round asked for ("is `role_mapping` consistent across `api.md`, `role_map.py`, D-10, `data.md`, D-11?"): `role_map.py`'s own inline comments — in the same security-sensitive file that guards D-10's privilege-escalation fix — contain two stale/self-contradicting statements that predate this round's diff and were missed in rounds 1-2. Neither affects runtime behavior (the mapping dict and its regression test are correct). Three LOW findings (main.py comment placement, `_ensure_database_exists` raw-SQL/no-timeout, `tasks.json` missing `F-21`/`F-22`) and one carried MEDIUM (`activity.jsonl` historical-row mutation) remain open exactly as round 2 left them — all four were weighed and consciously carried per this round's brief, not overlooked. No CRITICAL or HIGH findings; no new scope-creep, ADR violation, or contract-drift introduced by the six-file delta.

🟢 F-2/F-4 (round 2) and validation's `role_mapping` carry-forward all independently re-verified fixed, not just trusted; no over-correction found in `manifest.py`'s rewritten docstring; `repopulate()` semantics confirmed identical to what it replaced
⚠️ new MEDIUM: `role_map.py`'s own comments misidentify which slugs are "mapped" and cite the wrong decision id for the anti-regression guard; `activity.jsonl` mutation unresolved for a third round (still uncommitted, won't reach the PR); three LOW carries unchanged
🛑 none

## Findings summary

| Severity | Count | Category distribution |
|----------|-------|------------------------|
| CRITICAL | 0 | — |
| HIGH     | 0 | — |
| MEDIUM   | 2 | scope-creep (1, carried), module-structure (1, new) |
| LOW      | 3 | module-structure (1, carried), safety-security (1, carried), scope-creep (1, carried) |

## Detailed findings

### CRITICAL

None.

### HIGH

None.

### MEDIUM

#### F-1 (carried 3rd round, was round-1 F-3 / round-2 F-1) — scope-creep: `docs/activity/activity.jsonl` still mutates historical entries for unrelated, already-completed stories

- Category: scope-creep
- Path: `docs/activity/activity.jsonl` (not in `tasks.json` `file_plan` F-01..F-20)
- Source: `tasks.json` `file_plan`; `.claude/rules/surgical-changes.md`
- Description: Unchanged for a third consecutive round. The same 4 pre-existing rows still show fields mutated relative to `main`: a `BED-03`-adjacent `/model` entry (`feature:null`), `AUTH-03`, `AUTH-01`, `ING-01` (re-confirmed this round via `git diff main -- docs/activity/activity.jsonl` — exactly these 4 rows removed/replaced, no new ones). Per this round's brief this stays deliberately uncommitted, so it will not reach the PR; it does not block this diff's merge, but the underlying question (is the harness's own activity ingestion mutating history, or is this expected late-finalization telemetry?) is still open after three review rounds and should be filed as its own issue rather than carried a fourth time implicitly.
- Suggested fix: unchanged from rounds 1-2 — confirm the mutation's origin and file it as its own ticket; do not let a future story inherit this as "normal."

#### F-2 (new) — module-structure: `role_map.py`'s own comments misstate which slugs are mapped and cite the wrong decision for the anti-regression guard

- Category: Module structure & boundaries
- Path: `services/api/app/core/role_map.py:40,54-55`
- Source: `docs/features/ING-10/DECISIONS.md` D-10; `.claude/rules/security-baseline.md` (accuracy of privilege-relevant documentation)
- Description: Two issues in the file that exists specifically to guard D-10's privilege-escalation fix. (1) Line 40: "Do not re-add it without a decision on the record -- see DECISIONS.md D-03." D-03 is the decision that *originally created* the `admin`→`cio` fold; D-10 is the one that *removed* it and is the actual guard against re-adding. A reader following this citation lands on the permissive decision, not the one that forbids the regression — backwards for a comment whose entire purpose is stopping that regression. (2) `map_role_slug()`'s own docstring, lines 54-55: "`None` means the slug is not one of the mapped roster roles (`dev`, `arch`, `pm`, `em`, `cxo`, `board_member`, `admin`)" literally lists `admin` as one of "the mapped roster roles," directly contradicting `_ROLE_SLUG_TO_PERSONA`'s six-key dict three lines above and the 18-line comment block immediately preceding it that explains, at length, why `admin` is excluded. Neither issue changes behavior — `_ROLE_SLUG_TO_PERSONA` has 6 keys, no `admin`, and `test_map_role_slug_admin_is_deliberately_unmapped_af01` (D-10) guards the regression correctly. Both predate this round's 6-file diff and were missed in rounds 1-2; surfaced now because this round explicitly asked whether `role_mapping` is consistent across `api.md`, `role_map.py`, D-10, `data.md`, D-11 — it is, everywhere except this file's own prose.
- Suggested fix: change line 40 to "see DECISIONS.md D-10"; reword lines 54-55 to something like "`None` means `slug` is not one of the six mapped roles (`dev`, `arch`, `pm`, `em`, `cxo`, `board_member`) — this includes `admin`, deliberately (D-10)." Two sentences, no logic change.

### LOW

#### F-3 (carried, was round-1 F-5 / round-2 F-3) — module-structure: `app/main.py`'s "ingest_router stays unregistered" comment still sits directly above `manifest_router`'s registration

- Category: Module structure & boundaries
- Path: `services/api/app/main.py:81-91`
- Source: `.claude/rules/pattern-consistency.md`
- Description: Unchanged for a third round — re-confirmed at current line numbers. Readability nit only; wiring is correct (`manifest_router` registered, `ingest_router` still never imported). Deliberately not fixed this round per the brief.
- Suggested fix: unchanged — move `app.include_router(manifest_router)` before the comment block, or move the comment after the always-registered block.

#### F-4 (carried, was round-2 F-5) — safety-security: `_ensure_database_exists` builds `CREATE DATABASE` via raw f-string identifier interpolation, no connect timeout

- Category: Safety & security
- Path: `services/api/tests/conftest.py:172-174` (execute call), `:169` (connect call)
- Source: `.claude/rules/security-baseline.md` ("no string-built SQL"); `.claude/rules/performance-baseline.md` ("I/O has explicit timeouts")
- Description: Unchanged — re-confirmed: `conn.execute(f'CREATE DATABASE "{dbname}"')` still interpolates the identifier directly rather than via `psycopg.sql.Identifier`; `psycopg.connect(admin, autocommit=True)` still has no `connect_timeout`. Realistic injection risk stays close to zero (test-only, derived from `settings.database_url` plus a regex-sanitized suffix, not an external trust boundary). Deliberately not fixed this round per the brief.
- Suggested fix: unchanged — wrap `dbname` in `psycopg.sql.Identifier(dbname).as_string(conn)`; add a short `connect_timeout` (e.g. 5s).

#### F-5 (carried, was round-2 F-6) — scope-creep: `tasks.json`'s `file_plan` still has no entries for the accepted-flag edits to `tests/conftest.py` / `tests/fixtures/prd_8_4_schema.json`

- Category: scope-creep
- Path: `docs/features/ING-10/tasks.json` (`file_plan` F-01..F-20 — neither file listed; re-confirmed no `F-21`/`F-22` added)
- Source: `tasks.json` `file_plan`; `.claude/rules/surgical-changes.md`
- Description: Unchanged — `services/api/tests/conftest.py` (AF-11, AF-14) and `services/api/tests/fixtures/prd_8_4_schema.json` (AF-05) are BED-01-owned files this story legitimately extended into (disclosed via `FLAGS.md`/`state.json .agent_flags[]`), but `tasks.json`'s `file_plan` — the scope-creep baseline this skill checks against — still has no corresponding entries. Deliberately not fixed this round per the brief.
- Suggested fix: unchanged — add `F-21`/`F-22` entries (action: `modify`, reason citing AF-11/AF-14/AF-05).

## Closed this round (verified, not re-opened)

- **Round-2 F-2 (MEDIUM)** — `manifest.py`'s module docstring no longer contradicts the AF-09 fix. Verified against the actual code, not just re-read: the router imports `log_ingest_manifest_write` (services/api/app/api/manifest.py:98) and calls it on its own 413 branch (:158-184) with values mirroring the service's own 413 branch; `manifest_ingest.py` still carries its own `_TEAM_ENTRY_CAP`/413 branch as defence-in-depth (unchanged, as the docstring now correctly describes); `ingest_auth.py`'s `_log_ingest_token_auth_failed` is confirmed private and never imported elsewhere, so the docstring's claim that it "stays entirely inside `ingest_auth.py`" holds; `test_over_cap_http_emits_ingest_manifest_write_af09` exists and asserts no PII on the newly-reachable path. No over-correction, no new inaccuracy — this is the round's top-requested check and it passes.
- **Round-2 F-4 (LOW)** — `repopulate()` is now genuinely used. `test_manifest_roster_removal.py:69` and `test_manifest_payload_cap.py:156` both `from tests.conftest import ... repopulate` and wrap their `select(...)` in it before `.execute()`. `repopulate(stmt)` (`conftest.py:144`) is defined as exactly `stmt.execution_options(populate_existing=True)` — the same call, same semantics, as the inline form it replaces. This was the round's second-most-requested check (whether the refactor could silently weaken AF-14's guard); confirmed it does not — no behavior change, only de-duplication. No third caller of the old inline pattern remains anywhere in `services/api/tests/` or `app/`.
- **Validation's round-2 carry-forward** — `api.md`'s `role_mapping`, `REQUIREMENTS.md:73`, `PLAN.md:118` all now read `dev|arch|pm|em|cxo|board_member` with `admin`'s removal cited to D-10/AF-01. Cross-checked against `role_map.py`'s actual `_ROLE_SLUG_TO_PERSONA` (6 keys, matches), `data.md`'s `role_semantics` (raw-slug storage, orthogonal to and unaffected by the mapping table's contents), and D-11 (separate amendment, already reconciled in round 2, still consistent). `api.md`'s new claim that "the Keycloak path made the same call in PR #235" is independently verified against `services/api/config/persona_role_map.yaml`'s own committed comment text and `git log --grep=235`, not taken on faith. The one residual gap this check turned up is `role_map.py`'s own prose, not these three docs — see new F-2 above.

## What went well

- All three claimed closures independently re-verified against current code/tests, not re-read from the prompt's description — including the round's own stated top risk (`repopulate()` semantic equivalence) and top question (docstring over-correction), both checked out clean.
- `api.md`'s new factual claim about PR #235 was cross-checked against `persona_role_map.yaml`'s actual committed text rather than trusted as narrated.
- Carried findings (F-1, F-3, F-4, F-5) were each re-confirmed still present at their current line numbers, not assumed unchanged from the round-2 report.
- No new scope-creep: `find -newer` against the round-2/round-3 boundary confirms only the six claimed files (plus the already-open `activity.jsonl` item) changed in the source tree this round.

## Recommendation

**PASS.** No CRITICAL or HIGH findings. 2 MEDIUM (one carried, deliberately unfixed and non-blocking since it stays uncommitted; one new but comment-only with no behavioral impact) and 3 LOW (all carried, all deliberately unfixed per this round's own triage) are within the ≤3-MEDIUM PASS threshold. This is the final round under the combined cap — F-1 (`activity.jsonl`) should be filed as a standalone issue rather than carried again implicitly; F-2 (new) and the three LOW carries are optional follow-ups, none blocking. Proceed to `/arh-security-review`.
